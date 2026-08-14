"""End-to-end acceptance suite for the one-call workflow boundary.

The deterministic suite exercises the real router, host compilers, orchestrator,
verification, memory, and recorder while replacing only the external MCP wire.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from .flight_recorder import FlightRecorder
from .memory import MemoryDMLAdapter
from .orchestrator import RhinoWorkflowGateway, WorkflowOrchestrator
from .rhino import RhinoClient


HOST_OPERATIONS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "rhino": {
        "create": [{"op": "create_point", "id": "probe", "point": [1, 2, 3]}, {"op": "set_attributes", "targets": ["$probe"], "name": "Acceptance Target", "layer": "Hermes::Acceptance"}],
        "modify": [{"op": "transform_in_place", "targets": ["00000000-0000-0000-0000-000000000001"], "translation": [1, 0, 0]}],
        "delete": [{"op": "delete", "targets": ["00000000-0000-0000-0000-000000000001"]}],
    },
    "blender": {
        "create": [{"op": "ensure_collection", "id": "probe", "name": "Acceptance Target"}],
        "modify": [{"op": "transform", "objects": ["Acceptance Target"], "location": [1, 0, 0]}],
        "delete": [{"op": "delete_objects", "objects": ["Acceptance Target"]}],
    },
    "freecad": {
        "create": [{"op": "create_box", "id": "probe", "name": "AcceptanceTarget", "length": 1, "width": 1, "height": 1}],
        "modify": [{"op": "transform", "target": "AcceptanceTarget", "translation": [1, 0, 0]}],
        "delete": [{"op": "delete", "target": "AcceptanceTarget"}],
    },
}


def _object(object_id: str, revision: int) -> dict[str, Any]:
    data = {"id": object_id, "name": "Acceptance Target", "kind": "solid", "layer": "Acceptance"}
    data["content_hash"] = sha256(f"{object_id}:{revision}".encode()).hexdigest()
    return data


@dataclass
class DeterministicMCPTransport:
    """Stateful, deterministic substitute for a host MCP connection."""

    host: str
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    revision: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)
    fault: str | None = None

    def seed(self) -> None:
        self.objects = {"00000000-0000-0000-0000-000000000001": _object("00000000-0000-0000-0000-000000000001", 0)}

    async def query(self, query: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"method": "query", "query": query})
        return {"host": self.host, "document": {"units": "meters"}, "document_revision": str(self.revision), "objects": list(self.objects.values())}

    async def mutate(self, operation: str, *, stale_revision: str | None = None) -> dict[str, Any]:
        self.calls.append({"method": "mutate", "operation": operation, "revision": stale_revision})
        if self.fault == "lost_response":
            raise TimeoutError("deterministic lost MCP response")
        if self.fault == "stale_revision" or (stale_revision is not None and stale_revision != str(self.revision)):
            return {"status": "blocked", "error": "document revision changed after the focused query"}
        before = set(self.objects)
        modified: list[str] = []
        if operation == "create":
            self.objects["acceptance-created"] = _object("acceptance-created", self.revision + 1)
        elif operation == "modify":
            target = next(iter(self.objects)); self.objects[target] = _object(target, self.revision + 1); modified = [target]
        elif operation == "delete":
            self.objects.pop(next(iter(self.objects)))
        self.revision += 1
        after = set(self.objects)
        created, deleted = sorted(after - before), sorted(before - after)
        if self.fault == "verification_failure":
            created = ["receipt-lied-about-this-id"]
        return {"schema_version": "1.0", "status": "completed", "transaction_id": f"{self.host}-{operation}", "created_ids": created, "deleted_ids": deleted, "modified_ids": modified}


class DeterministicWorkflowGateway:
    def __init__(self, transport: DeterministicMCPTransport, operation: str) -> None:
        self.transport, self.operation = transport, operation

    async def query(self, query: dict[str, Any]) -> dict[str, Any]:
        return await self.transport.query(query)

    async def execute_typed(self, **kwargs: Any) -> dict[str, Any]:
        return await self.transport.mutate(self.operation, stale_revision=kwargs.get("document_revision"))


async def _scenario(host: str, behavior: str, trace_path: Path) -> dict[str, Any]:
    operation = behavior if behavior in {"create", "modify", "delete"} else "modify"
    transport = DeterministicMCPTransport(host, fault=behavior if behavior not in {"create", "modify", "delete"} else None)
    if operation != "create": transport.seed()
    gateway = DeterministicWorkflowGateway(transport, operation)
    runner = WorkflowOrchestrator({host: gateway}, recorder=FlightRecorder(trace_path), memory=MemoryDMLAdapter())
    verb = {"create": "add", "modify": "move", "delete": "delete"}[operation]
    result = await runner.run(
        request=f"{verb} acceptance target", operations=HOST_OPERATIONS[host][operation], active_host=host,
        idempotency_key=f"acceptance:{host}:{behavior}", assertions={"object_count_delta": {"create": 1, "modify": 0, "delete": -1}[operation]},
    )
    expected = {"lost_response": "unknown", "stale_revision": "blocked", "verification_failure": "unverified"}.get(behavior, "verified")
    return {"host": host, "scenario": behavior, "expected": expected, "actual": result.status, "passed": result.status == expected, "transport_calls": transport.calls, "result": result.to_dict()}


async def run_deterministic_acceptance(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "acceptance-flight.jsonl"
    if trace_path.exists(): trace_path.unlink()
    results = [await _scenario(host, behavior, trace_path) for host in HOST_OPERATIONS for behavior in ("create", "modify", "delete", "lost_response", "stale_revision", "verification_failure")]
    report = {"schema_version": "aec-acceptance/1.0", "mode": "deterministic", "passed": all(item["passed"] for item in results), "scenario_count": len(results), "results": results, "trace_path": str(trace_path)}
    (output_dir / "acceptance-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


async def run_live_rhino_acceptance(*, confirmation: str) -> dict[str, Any]:
    """Create and remove one probe; fail unless the final object identity set is exact."""
    if os.environ.get("HERMES_AEC_LIVE_ACCEPTANCE") != "1" or confirmation != "I_ACCEPT_REVERSIBLE_RHINO_MUTATION":
        raise PermissionError("live acceptance requires HERMES_AEC_LIVE_ACCEPTANCE=1 and the exact confirmation phrase")
    client = RhinoClient()
    gateway = RhinoWorkflowGateway(client)
    runner = WorkflowOrchestrator({"rhino": gateway})
    before = await client.scene_query(query={"limit": 5000})
    before_ids = {str(item["id"]) for item in before.get("objects", [])}
    key = f"live-acceptance:{uuid4()}"
    created_ids: list[str] = []
    try:
        result = await runner.run(request="add acceptance target", operations=HOST_OPERATIONS["rhino"]["create"], active_host="rhino", idempotency_key=key, assertions={"object_count_delta": 1, "names_present": ["Acceptance Target"]})
        receipt = result.receipt or {}
        if receipt.get("status") != "completed": raise RuntimeError(f"probe creation did not complete: {receipt}")
        if result.status != "verified": raise RuntimeError(f"one-call probe creation was not independently verified: {result.verification}")
        created_ids = list(receipt.get("created_ids") or (receipt.get("operation_result") or {}).get("created") or [])
        if len(created_ids) != 1: raise RuntimeError(f"expected exactly one probe ID: {receipt}")
    finally:
        if created_ids:
            cleanup = await gateway.execute_typed(intent="modify", operations=[{"op": "delete", "targets": created_ids}], idempotency_key=f"{key}:cleanup", dry_run=False, document_revision=await client.document_revision())
            if cleanup.get("status") != "completed": raise RuntimeError(f"probe cleanup did not complete: {cleanup}")
    after = await client.scene_query(query={"limit": 5000})
    after_ids = {str(item["id"]) for item in after.get("objects", [])}
    residue = sorted(after_ids - before_ids)
    missing = sorted(before_ids - after_ids)
    if residue or missing: raise RuntimeError(f"live acceptance did not restore identity set: residue={residue}, missing={missing}")
    return {"schema_version": "aec-acceptance/1.0", "mode": "live-rhino", "passed": True, "created_and_removed": created_ids, "zero_residue": True, "object_count": len(after_ids)}
