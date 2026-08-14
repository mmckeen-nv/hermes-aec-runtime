from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .contracts import AECTransaction, AECAction
from .runtime import assemble_transaction, execute_transaction, preprocess_scene, route_context
from .rhino import RhinoClient
from .operations import OperationValidationError, compile_transaction
from .verification import verify_transaction
from .router import route_request
from .blender import BlenderGateway, default_transport, recovery_plan as blender_recovery_plan, validate_handoff_manifest
from .memory import FilesystemDMLAdapter, create_outcome
from .flight_recorder import FlightRecorder, make_trace
from .freecad import FreeCADGateway, freecad_recovery_plan
from .orchestrator import BlenderWorkflowGateway, FreeCADWorkflowGateway, RhinoWorkflowGateway, WorkflowOrchestrator, build_plan
from .observability import ExecutionBudget, readiness, storage_ready
from .rhinomcp_transport import RhinoMCPGateway
import os
from pathlib import Path

mcp = FastMCP("Hermes AEC Runtime")
_blender = BlenderGateway(default_transport)
_memory = FilesystemDMLAdapter(Path(os.environ.get("HERMES_AEC_MEMORY_ROOT", ".hermes-aec-memory")))
_recorder = FlightRecorder(Path(os.environ.get("HERMES_AEC_TRACE_PATH", ".hermes-aec-traces/traces.jsonl")))
_freecad = FreeCADGateway()
_rhino_direct = RhinoMCPGateway()
_workflow = WorkflowOrchestrator(
    {"rhino": RhinoWorkflowGateway(RhinoClient()), "blender": BlenderWorkflowGateway(_blender), "freecad": FreeCADWorkflowGateway(_freecad)},
    recorder=_recorder, memory=_memory,
)


@mcp.tool()
def scene_preprocessing(snapshot: dict) -> dict:
    """Normalize an AEC host snapshot into the compact SceneIndex contract."""
    return preprocess_scene(snapshot).to_dict()


@mcp.tool()
def request_context_routing(request: str, scene_index: dict, limit: int = 40) -> dict:
    """Return only scene objects relevant to a natural-language AEC request."""
    scene = preprocess_scene(scene_index)
    return {"request": request, "objects": [obj.__dict__ for obj in route_context(request, scene, limit)]}


@mcp.tool()
def route_aec_request(request: str, active_host: str = "rhino") -> dict:
    """Classify an AEC request and return the minimal host, workflow stages, tools, risk, web need, and target terms."""
    return route_request(request, active_host=active_host).to_dict()


@mcp.tool()
def aec_workflow_plan(request: str, operations: list[dict] | None = None, active_host: str = "rhino", query_limit: int = 40) -> dict:
    """Route and validate an entire AEC request before any host call or mutation."""
    return build_plan(request, operations or (), active_host=active_host, query_limit=query_limit).to_dict()


@mcp.tool()
async def aec_run_workflow(request: str, operations: list[dict] | None = None, active_host: str = "rhino", idempotency_key: str = "", dry_run: bool = False, assertions: dict | None = None, project_id: str = "default", model: dict | None = None, token_usage: dict | None = None, budget: dict | None = None, correlation_id: str | None = None) -> dict:
    """Run focused query, one typed mutation, independent verification, memory promotion, and trace recording as one deterministic workflow."""
    limits = ExecutionBudget.from_mapping(budget)
    result = await _workflow.run(request=request, operations=operations or (), active_host=active_host, idempotency_key=idempotency_key, dry_run=dry_run, assertions=assertions, project_id=project_id, model=model, token_usage=token_usage, budget=limits, correlation_id=correlation_id)
    return result.to_dict()


@mcp.tool()
async def aec_runtime_health(active_host: str | None = None, timeout_seconds: float = 5.0) -> dict:
    """Report sidecar readiness; optionally prove a configured host can answer a bounded read."""
    async def local_storage() -> None:
        if not storage_ready(_recorder.path):
            raise RuntimeError("trace storage is unavailable")

    probes = {"flight_recorder": local_storage}
    if active_host:
        host_name = active_host.lower()
        gateway = _workflow.gateways.get(host_name)
        if gateway is None:
            async def missing_host() -> None: raise RuntimeError("host is not configured")
            probes["requested_host"] = missing_host
        else:
            async def host_read() -> None:
                await gateway.query({"terms": [], "limit": 1})
            probes[f"host:{host_name}"] = host_read
    return await readiness(probes, timeout_seconds=timeout_seconds)


@mcp.tool()
async def freecad_scene_query() -> dict:
    """Return a compact index of the active FreeCAD document through FreeCAD MCP."""
    return await _freecad.scene_query()


@mcp.tool()
async def freecad_apply_operations(intent: str, operations: list[dict], idempotency_key: str, dry_run: bool = False) -> dict:
    """Validate and apply one typed FreeCAD document transaction."""
    return await _freecad.execute(intent=intent, operations=operations, idempotency_key=idempotency_key, dry_run=dry_run)


@mcp.tool()
def freecad_proof_and_recovery(receipt: dict) -> dict:
    """Return the verify or reconcile plan for a FreeCAD transaction receipt."""
    return freecad_recovery_plan(receipt)


@mcp.tool()
async def blender_scene_query() -> dict:
    """Return a compact, revisioned index of the active Blender scene."""
    return await _blender.scene_preprocessing()


@mcp.tool()
async def blender_apply_operations(intent: str, operations: list[dict], idempotency_key: str, dry_run: bool = False) -> dict:
    """Compile and apply one typed Blender transaction through the standard Blender MCP."""
    return await _blender.execute(intent=intent, operations=operations, idempotency_key=idempotency_key, dry_run=dry_run)


@mcp.tool()
def blender_validate_handoff(manifest: dict) -> dict:
    """Validate Rhino-to-Blender object IDs, units, layers, and export path before import."""
    return validate_handoff_manifest(manifest)


@mcp.tool()
def blender_proof_and_recovery(receipt: dict) -> dict:
    """Return the deterministic verify/reconcile/rollback plan for a Blender receipt."""
    return blender_recovery_plan(receipt)


@mcp.tool()
def workflow_memory_promote(project_id: str, host: str, receipt: dict, verification: dict, operation_signature: str, trace: list[dict] | None = None) -> dict:
    """Score, sanitize, deduplicate, and persist a verified execution outcome for DML ingestion."""
    outcome = create_outcome(project_id=project_id, host=host, receipt=receipt, verification=verification, trace=trace or (), operation_signature=operation_signature)
    inserted = _memory.put(outcome)
    return {**outcome.to_dict(), "inserted": inserted}


@mcp.tool()
def workflow_memory_query(project_id: str, host: str, status: str | None = "promoted") -> dict:
    """Return sanitized workflow outcomes for the requested project and host."""
    return {"outcomes": [item.to_dict() for item in _memory.list(project_id, host, status)]}


@mcp.tool()
def flight_recorder_record(request: str, route: dict, scene_subset: dict, transaction: dict, timing: dict, tool_outcomes: list[dict], receipt: dict, verification: dict, recovery: dict | None = None, model: dict | None = None, token_usage: dict | None = None) -> dict:
    """Append one sanitized execution trace and report whether it qualifies for model training."""
    trace = make_trace(request=request, route=route, scene_subset=scene_subset, transaction=transaction, timing=timing, tool_outcomes=tool_outcomes, receipt=receipt, verification=verification, recovery=recovery, model=model, token_usage=token_usage)
    inserted = _recorder.append(trace)
    return {"trace_id": trace["trace_id"], "inserted": inserted, "training_quality": trace["training_quality"]}


@mcp.tool()
def action_assembly(
    request: str,
    host: str,
    operation: str,
    target_ids: list[str] | None = None,
    parameters: dict | None = None,
    dry_run: bool = True,
) -> dict:
    """Compile one explicit semantic operation into a reviewable AEC transaction."""
    return assemble_transaction(request, host, operation, target_ids or (), parameters, dry_run).to_dict()


@mcp.tool()
def proof_and_recovery(transaction: dict) -> dict:
    """Execute or validate an AEC transaction and return a durable receipt."""
    actions = tuple(AECAction(**action) for action in transaction["actions"])
    typed = AECTransaction(
        request=transaction["request"], host=transaction["host"], actions=actions,
        transaction_id=transaction["transaction_id"], dry_run=transaction.get("dry_run", True),
    )
    return execute_transaction(typed).to_dict()


@mcp.tool()
async def rhino_scene_preprocessing(
    names: list[str] | None = None,
    layer: str | None = None,
    geometry_type: str | None = None,
    include_hidden: bool = True,
    limit: int = 5000,
) -> dict:
    """Index the active Rhino document or a filtered subset using stable object IDs."""
    return await RhinoClient().scene_index(
        names=names, layer=layer, geometry_type=geometry_type,
        include_hidden=include_hidden, limit=limit,
    )


@mcp.tool()
async def rhino_execute_python(
    intent: str,
    script: str,
    expected_change: str,
    dry_run: bool = True,
    idempotency_key: str | None = None,
) -> dict:
    """Validate or execute one bounded Rhino Python/RhinoCommon mutation. Use __rhino_doc__ and a unique stable idempotency_key. The sidecar serializes access, persists receipts, reconciles lost responses, and rolls back script failures."""
    return await RhinoClient().execute_python(
        intent=intent, script=script, expected_change=expected_change,
        dry_run=dry_run, idempotency_key=idempotency_key,
    )


@mcp.tool()
async def rhino_verify(
    names: list[str] | None = None,
    layer: str | None = None,
    geometry_type: str | None = None,
    limit: int = 5000,
) -> dict:
    """Independently verify Rhino objects after a mutation; filter by expected names, layer, or type."""
    return await RhinoClient().scene_index(
        names=names, layer=layer, geometry_type=geometry_type,
        include_hidden=True, limit=limit,
    )


@mcp.tool()
async def rhino_health() -> dict:
    """Check the Rhino MCP bridge and report latency, connection, retry, and failure counters."""
    return await _rhino_direct.health()


@mcp.tool()
async def rhino_scene_query(query: dict | None = None, audit_limit: int = 2000) -> dict:
    """Run one rich, revisioned Rhino audit and return only objects matching focused name, layer, kind, ID, relationship, proximity, containment, or intersection selectors."""
    scene = await _rhino_direct.scene_index(max_objects=audit_limit)
    if not query:
        return scene
    objects = scene.get("objects", [])
    ids = {str(value) for value in query.get("ids", [])} if query.get("ids") else None
    name = str(query.get("name", "")).casefold()
    layer = str(query.get("layer", "")).casefold()
    kind = str(query.get("kind", query.get("geometry_type", ""))).casefold()
    selected = []
    for item in objects:
        if ids is not None and str(item.get("id")) not in ids:
            continue
        if name and name not in str(item.get("name", "")).casefold():
            continue
        if layer and layer not in str(item.get("layer", "")).casefold():
            continue
        if kind and kind != str(item.get("type", item.get("kind", ""))).casefold():
            continue
        selected.append(item)
        if len(selected) >= int(query.get("limit", 100)):
            break
    return {**scene, "objects": selected, "count": len(selected), "query": query}


@mcp.tool()
async def rhino_apply_operations(
    intent: str,
    operations: list[dict],
    idempotency_key: str,
    document_revision: str,
    dry_run: bool = False,
    checkpoint_path: str | None = None,
) -> dict:
    """Validate and execute one typed Rhino operation batch. Supports primitives, in-place transforms, duplicate/delete, attributes, extrusion, offset, and booleans without model-generated RhinoCommon."""
    receipt = await _rhino_direct.execute_operations(
        intent=intent,
        operations=operations,
        dry_run=dry_run,
        idempotency_key=idempotency_key,
        document_revision=document_revision,
    )
    if receipt.get("status") == "completed" and checkpoint_path and not dry_run:
        try:
            checkpoint = await RhinoClient().save_checkpoint(checkpoint_path)
            receipt["checkpoint"] = {"path": checkpoint_path, "status": "saved", "host_result": checkpoint}
        except Exception as exc:
            receipt["checkpoint"] = {"path": checkpoint_path, "status": "unknown", "error": str(exc)}
    return {
        **receipt,
        "semantic_fingerprint": receipt.get("fingerprint"),
        "normalized_transaction": {"operations": operations},
    }


@mcp.tool()
def rhino_verify_transaction(
    receipt: dict,
    before_scene: dict,
    after_scene: dict,
    assertions: dict | None = None,
) -> dict:
    """Compare a transaction receipt with independent before/after scene snapshots and explicit invariants."""
    return verify_transaction(receipt, before_scene, after_scene, assertions).to_dict()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
