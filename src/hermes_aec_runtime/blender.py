"""Resilient Blender MCP gateway and Rhino-to-Blender handoff validation."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Awaitable, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .blender_operations import compile_blender_transaction


class BlenderUnavailable(RuntimeError): pass


class BlenderTransport(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class StdioBlenderTransport:
    """Connect to the standard Blender MCP without exposing raw code to Hermes."""

    command: str = "uvx"
    args: tuple[str, ...] = ("blender-mcp",)

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        parameters = StdioServerParameters(command=self.command, args=list(self.args))
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
        if result.isError:
            detail = " ".join(getattr(item, "text", "") for item in result.content)
            raise BlenderUnavailable(detail or f"Blender MCP tool {tool} failed")
        if result.structuredContent is not None:
            return dict(result.structuredContent)
        texts = [getattr(item, "text", "") for item in result.content]
        if len(texts) == 1:
            try:
                decoded = json.loads(texts[0])
                return decoded if isinstance(decoded, dict) else {"result": decoded}
            except json.JSONDecodeError:
                pass
        return {"content": texts}


def default_transport() -> StdioBlenderTransport:
    command = os.environ.get("HERMES_AEC_BLENDER_COMMAND", "uvx")
    args = tuple(filter(None, os.environ.get("HERMES_AEC_BLENDER_ARGS", "blender-mcp").split()))
    return StdioBlenderTransport(command=command, args=args)


@dataclass
class BlenderGateway:
    transport_factory: Callable[[], BlenderTransport]
    read_attempts: int = 3
    timeout_seconds: float = 90
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _receipts: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    async def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.wait_for(self.transport_factory().call(tool, args), self.timeout_seconds)

    async def _read(self, operation: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        async with self._lock:
            error: Exception | None = None
            for attempt in range(self.read_attempts):
                try: return await operation()
                except Exception as exc:
                    error = exc
                    if attempt + 1 < self.read_attempts: await asyncio.sleep(.05 * 2**attempt)
            raise BlenderUnavailable(f"Blender read failed after {self.read_attempts} attempts: {error}")

    async def scene_preprocessing(self) -> dict[str, Any]:
        payload = await self._read(lambda: self._call("get_scene_info", {}))
        objects = []
        for raw in payload.get("objects", []):
            objects.append({
                "id": str(raw.get("id") or raw.get("name")), "name": str(raw.get("name", "")),
                "kind": str(raw.get("type", "UNKNOWN")), "layer": str(raw.get("collection", "Scene Collection")),
                "properties": {k: raw[k] for k in ("location", "rotation", "scale", "bounds", "materials") if k in raw},
            })
        canonical = json.dumps(objects, sort_keys=True, separators=(",", ":"))
        return {
            "schema_version": "1.0", "host": "blender",
            "document_id": str(payload.get("document_id", payload.get("file", "unsaved"))),
            "units": str(payload.get("units", "meters")), "objects": objects,
            "document_revision": sha256(canonical.encode()).hexdigest(),
        }

    async def execute(self, *, intent: str, operations: list[dict[str, Any]], idempotency_key: str, dry_run: bool = False) -> dict[str, Any]:
        if not idempotency_key.strip(): raise ValueError("idempotency_key is required")
        compiled = compile_blender_transaction(operations)
        transaction_id = str(uuid5(NAMESPACE_URL, idempotency_key))
        prior = self._receipts.get(idempotency_key)
        if prior:
            if prior["fingerprint"] == compiled.fingerprint: return {**prior, "replayed": True}
            return {"status": "blocked", "transaction_id": transaction_id, "error": "idempotency key is bound to another payload", "prior_receipt": prior}
        if dry_run:
            return {"status": "validated", "transaction_id": transaction_id, "fingerprint": compiled.fingerprint, "normalized": compiled.normalized}
        async with self._lock:
            try:
                result = await self._call("execute_blender_code", {"code": compiled.script})
            except Exception as exc:
                return {"status": "unknown", "transaction_id": transaction_id, "fingerprint": compiled.fingerprint, "error": str(exc), "recovery": "Inspect the scene, then retry with the same idempotency key."}
        receipt = {"schema_version": "1.0", "host": "blender", "status": "completed", "transaction_id": transaction_id, "intent": intent, "fingerprint": compiled.fingerprint, "result": result}
        self._receipts[idempotency_key] = receipt
        return receipt


def validate_handoff_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate an explicit Rhino export manifest before Blender import."""
    errors: list[str] = []
    if manifest.get("schema_version") != "1.0": errors.append("schema_version must be 1.0")
    if manifest.get("source_host") != "rhino": errors.append("source_host must be rhino")
    if manifest.get("units") not in {"millimeters", "centimeters", "meters", "inches", "feet"}: errors.append("units must be explicit and supported")
    if not isinstance(manifest.get("export_path"), str) or not manifest.get("export_path", "").strip(): errors.append("export_path is required")
    objects = manifest.get("objects")
    if not isinstance(objects, list) or not objects: errors.append("objects must be a non-empty array")
    else:
        ids: set[str] = set()
        for i, obj in enumerate(objects):
            if not isinstance(obj, dict): errors.append(f"objects[{i}] must be an object"); continue
            for field in ("rhino_id", "layer"):
                if not isinstance(obj.get(field), str) or not obj[field].strip(): errors.append(f"objects[{i}].{field} is required")
            rid = obj.get("rhino_id")
            if rid in ids: errors.append(f"objects[{i}].rhino_id is duplicated")
            ids.add(rid)
    return {"valid": not errors, "errors": errors, "object_count": len(objects) if isinstance(objects, list) else 0, "unit_scale_to_meters": {"millimeters": .001, "centimeters": .01, "meters": 1, "inches": .0254, "feet": .3048}.get(manifest.get("units"))}


def recovery_plan(receipt: dict[str, Any]) -> dict[str, Any]:
    status = receipt.get("status")
    if status == "unknown": return {"action": "reconcile", "steps": ["Re-index the Blender scene", "Check intended outputs", "Retry only with the same idempotency key"]}
    if status == "failed": return {"action": "rollback", "steps": ["Undo the transaction once", "Re-index and verify", "Correct the operation and use a new key"]}
    return {"action": "verify", "steps": ["Re-index changed objects", "Validate handoff IDs and rendered outputs"]}
