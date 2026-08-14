"""Deterministic end-to-end AEC workflow orchestration.

The orchestrator owns sequencing and evidence, never a host connection.  Host
mutation remains behind a small gateway protocol so planning can be tested and
dry-run without Rhino or Blender running.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol, Sequence

from .blender_operations import compile_blender_transaction
from .flight_recorder import FlightRecorder, make_trace
from .memory import DMLAdapter, MemoryOutcome, create_outcome
from .operations import compile_transaction
from .freecad_operations import compile_freecad_transaction
from .router import RequestRoute, route_request
from .verification import verify_transaction


class WorkflowGateway(Protocol):
    """Only capability the coordinator needs from a host adapter."""

    async def query(self, query: dict[str, Any]) -> dict[str, Any]: ...
    async def execute_typed(
        self, *, intent: str, operations: list[dict[str, Any]],
        idempotency_key: str, dry_run: bool,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FocusedQuery:
    terms: tuple[str, ...]
    limit: int = 40

    def to_dict(self) -> dict[str, Any]:
        # Rhino's query language accepts name_contains; gateways may additionally
        # use terms for local semantic indexes.
        return {"terms": list(self.terms), "name_contains": " ".join(self.terms), "limit": self.limit}


@dataclass(frozen=True)
class WorkflowPlan:
    route: RequestRoute
    query: FocusedQuery
    operations: tuple[dict[str, Any], ...]
    normalized_transaction: dict[str, Any] | None
    operation_signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "aec-workflow-plan/1.0", "route": self.route.to_dict(),
            "focused_query": self.query.to_dict(), "operations": list(self.operations),
            "transaction": self.normalized_transaction,
            "operation_signature": self.operation_signature,
        }


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    plan: WorkflowPlan
    before: dict[str, Any]
    receipt: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    memory: MemoryOutcome | None = None
    trace_id: str | None = None
    trace_appended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "aec-workflow-result/1.0", "status": self.status,
            "plan": self.plan.to_dict(), "before": self.before, "receipt": self.receipt,
            "after": self.after, "verification": self.verification,
            "memory": self.memory.to_dict() if self.memory else None,
            "trace_id": self.trace_id, "trace_appended": self.trace_appended,
        }


def build_plan(
    request: str, operations: Sequence[dict[str, Any]] = (), *,
    active_host: str = "rhino", query_limit: int = 40,
) -> WorkflowPlan:
    """Route and validate work before any host call is possible."""
    route = route_request(request, active_host=active_host)
    ops = tuple(dict(op) for op in operations)
    if route.mutates and not ops:
        raise ValueError("a mutating route requires at least one typed operation")
    if not route.mutates and ops:
        raise ValueError("read-only routes cannot contain operations")
    normalized = None
    signature = "read-only"
    if ops:
        if route.host == "blender": compiled = compile_blender_transaction(ops)
        elif route.host == "freecad": compiled = compile_freecad_transaction(list(ops))
        else: compiled = compile_transaction(ops)
        normalized = compiled.normalized
        signature = compiled.fingerprint
    return WorkflowPlan(route, FocusedQuery(route.target_terms, query_limit), ops, normalized, signature)


class WorkflowOrchestrator:
    def __init__(
        self, gateways: dict[str, WorkflowGateway], *, recorder: FlightRecorder | None = None,
        memory: DMLAdapter | None = None,
    ) -> None:
        self.gateways = {name.lower(): value for name, value in gateways.items()}
        self.recorder = recorder
        self.memory = memory

    async def run(
        self, *, request: str, operations: Sequence[dict[str, Any]] = (),
        active_host: str = "rhino", idempotency_key: str = "", dry_run: bool = False,
        assertions: dict[str, Any] | None = None, project_id: str = "default",
        model: dict[str, Any] | None = None, token_usage: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        plan = build_plan(request, operations, active_host=active_host)
        gateway = self.gateways.get(plan.route.host)
        if gateway is None:
            raise ValueError(f"no workflow gateway configured for host {plan.route.host!r}")
        started = perf_counter()
        before = await gateway.query(plan.query.to_dict())
        if not plan.route.mutates:
            return WorkflowResult("inspected", plan, before)
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required for mutations")

        try:
            receipt = await gateway.execute_typed(
                intent=plan.route.intent.value, operations=list(plan.operations),
                idempotency_key=idempotency_key, dry_run=dry_run,
            )
        except Exception as exc:
            # A lost mutation response is ambiguous. Never retry it here; persist
            # enough evidence for the host recovery path to reconcile it.
            receipt = {
                "schema_version": "1.0", "status": "unknown", "transaction_id": None,
                "error": f"{type(exc).__name__}: {exc}",
                "recovery": "Re-index the host and reconcile before retrying with the same idempotency key.",
            }
        receipt = dict(receipt)
        receipt.setdefault("actions_attempted", len(plan.operations))
        receipt.setdefault("actions_completed", len(plan.operations) if receipt.get("status") == "completed" else 0)
        if dry_run or receipt.get("status") != "completed":
            verification = {"schema_version": "1.0", "status": "not_run", "passed": [], "failed": ["host mutation did not complete"]}
            return await self._finish(plan, request, before, None, receipt, verification, project_id, started, model, token_usage)

        try:
            after = await gateway.query(plan.query.to_dict())
            verification = verify_transaction(receipt, before, after, assertions).to_dict()
        except Exception as exc:
            after = None
            verification = {
                "schema_version": "1.0", "status": "failed", "passed": [],
                "failed": [f"post-mutation scene query failed: {type(exc).__name__}: {exc}"],
                "transaction_id": receipt.get("transaction_id"),
            }
        return await self._finish(plan, request, before, after, receipt, verification, project_id, started, model, token_usage)

    async def _finish(
        self, plan: WorkflowPlan, request: str, before: dict[str, Any], after: dict[str, Any] | None,
        receipt: dict[str, Any], verification: dict[str, Any], project_id: str, started: float,
        model: dict[str, Any] | None, token_usage: dict[str, Any] | None,
    ) -> WorkflowResult:
        outcome = create_outcome(
            project_id=project_id, host=plan.route.host, receipt=receipt,
            verification=verification, operation_signature=plan.operation_signature,
        )
        if self.memory is not None:
            self.memory.put(outcome)
        trace = make_trace(
            request=request, route=plan.route.to_dict(), scene_subset=before,
            transaction=plan.normalized_transaction or {},
            timing={"total_ms": round((perf_counter() - started) * 1000, 3)}, tool_outcomes=[],
            receipt=receipt, verification=verification, model=model, token_usage=token_usage,
        )
        appended = self.recorder.append(trace) if self.recorder is not None else False
        status = (
            "verified" if verification.get("status") == "verified" else
            "unverified" if receipt.get("status") == "completed" else receipt.get("status", "failed")
        )
        return WorkflowResult(status, plan, before, receipt, after, verification, outcome, trace["trace_id"], appended)


class RhinoWorkflowGateway:
    """Adapter over the existing RhinoClient; all mutation stays in that client."""
    def __init__(self, client: Any) -> None: self.client = client
    async def query(self, query: dict[str, Any]) -> dict[str, Any]:
        # The Rhino rich index has exact/spatial selectors. Fetch a bounded index
        # and rank locally when the request only provides natural-language terms.
        scene = await self.client.scene_query(query={"limit": 2000})
        return _focus_scene(scene, query)
    async def execute_typed(self, *, intent: str, operations: list[dict[str, Any]], idempotency_key: str, dry_run: bool) -> dict[str, Any]:
        compiled = compile_transaction(operations)
        return await self.client.execute_python(intent=intent, script=compiled.script, expected_change=compiled.expected_change, dry_run=dry_run, idempotency_key=idempotency_key)


class BlenderWorkflowGateway:
    """Adapter over the existing BlenderGateway."""
    def __init__(self, gateway: Any) -> None: self.gateway = gateway
    async def query(self, query: dict[str, Any]) -> dict[str, Any]:
        return _focus_scene(await self.gateway.scene_preprocessing(), query)
    async def execute_typed(self, *, intent: str, operations: list[dict[str, Any]], idempotency_key: str, dry_run: bool) -> dict[str, Any]:
        return await self.gateway.execute(intent=intent, operations=operations, idempotency_key=idempotency_key, dry_run=dry_run)


class FreeCADWorkflowGateway:
    """Adapter over the typed FreeCAD gateway."""
    def __init__(self, gateway: Any) -> None: self.gateway = gateway
    async def query(self, query: dict[str, Any]) -> dict[str, Any]:
        return _focus_scene(await self.gateway.scene_query(), query)
    async def execute_typed(self, *, intent: str, operations: list[dict[str, Any]], idempotency_key: str, dry_run: bool) -> dict[str, Any]:
        return await self.gateway.execute(intent=intent, operations=operations, idempotency_key=idempotency_key, dry_run=dry_run)


def _focus_scene(scene: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    terms = tuple(str(term).casefold() for term in query.get("terms", ()))
    if not terms:
        return scene
    ranked = [
        (sum(term in f"{obj.get('name','')} {obj.get('kind','')} {obj.get('layer','')}".casefold() for term in terms), obj)
        for obj in scene.get("objects", ())
    ]
    matches = [
        obj for score, obj in sorted(ranked, key=lambda item: (-item[0], str(item[1].get("id")))) if score
    ]
    return {**scene, "objects": matches[:int(query.get("limit", 40))], "query_count": len(matches)}
