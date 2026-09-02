from __future__ import annotations

from mcp.server.fastmcp import FastMCP, Image

from .contracts import AECTransaction, AECAction
from .runtime import assemble_transaction, execute_transaction, preprocess_scene, route_context
from .rhino import RhinoClient
from .operations import OperationValidationError, compile_transaction
from .verification import verify_transaction
from .router import route_request
from .blender import BlenderGateway, default_transport, recovery_plan as blender_recovery_plan, validate_handoff_manifest
from .comfyui import ComfyUIGateway, default_transport as default_comfyui_transport
from .memory import FilesystemDMLAdapter, create_outcome
from .flight_recorder import FlightRecorder, make_trace
from .freecad import FreeCADGateway, freecad_recovery_plan
from .orchestrator import BlenderWorkflowGateway, FreeCADWorkflowGateway, RhinoWorkflowGateway, WorkflowOrchestrator, build_plan
from .observability import ExecutionBudget, readiness, storage_ready
from .rhinomcp_transport import RhinoMCPGateway
from .operation_models import RhinoOperationInput, dump_operations
from .blender_operation_models import BlenderOperationInput, dump_blender_operations
from .scene_query_models import RhinoSceneQuery, normalize_scene_query
from collections import Counter
import base64
import os
from pathlib import Path
from typing import Literal

mcp = FastMCP("Hermes AEC Runtime")
_blender = BlenderGateway(default_transport)
_comfyui = ComfyUIGateway(default_comfyui_transport())
_memory = FilesystemDMLAdapter(Path(os.environ.get("HERMES_AEC_MEMORY_ROOT", ".hermes-aec-memory")))
_recorder = FlightRecorder(Path(os.environ.get("HERMES_AEC_TRACE_PATH", ".hermes-aec-traces/traces.jsonl")))
_freecad = FreeCADGateway()
_rhino_direct = RhinoMCPGateway()
_workflow = WorkflowOrchestrator(
    {"rhino": RhinoWorkflowGateway(_rhino_direct), "blender": BlenderWorkflowGateway(_blender), "freecad": FreeCADWorkflowGateway(_freecad)},
    recorder=_recorder, memory=_memory,
)

_HDRI_PRESETS = {
    "daylight": {
        "filename": "quadrangle_cloudy_2k.hdr", "strength": 0.85, "rotation_degrees": 110.0,
        "sun_rotation": (35.0, -20.0, -40.0), "sun_energy": 2.0, "fill_energy": 900.0,
    },
    "golden_hour": {
        "filename": "safari_sunset_2k.hdr", "strength": 0.9, "rotation_degrees": 225.0,
        "sun_rotation": (65.0, -10.0, -120.0), "sun_energy": 3.5, "fill_energy": 700.0,
    },
    "studio": {
        "filename": "studio_small_02_2k.hdr", "strength": 0.65, "rotation_degrees": 25.0,
        "sun_rotation": (28.0, -18.0, -35.0), "sun_energy": 1.0, "fill_energy": 1600.0,
    },
}


def _managed_hdri_path(preset: str) -> tuple[Path, dict]:
    settings = _HDRI_PRESETS[preset]
    configured = os.environ.get("HERMES_AEC_HDRI_ROOT")
    root = Path(configured) if configured else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "hermes" / "integrations" / "blender-hdri" / "polyhaven-2k"
    path = root / settings["filename"]
    if not path.is_file():
        raise ValueError(f"Managed Blender HDRI preset '{preset}' is missing at {path}; rerun AEC deployment with Blender enabled")
    return path, settings


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
def aec_workflow_plan(request: str, operations: list[RhinoOperationInput] | None = None, active_host: str = "rhino", query_limit: int = 40) -> dict:
    """Route and validate an AEC request. Rhino operations use the exact per-op schema shown here; names/layers belong in a separate set_attributes operation."""
    return build_plan(request, dump_operations(operations), active_host=active_host, query_limit=query_limit).to_dict()


@mcp.tool()
async def aec_run_workflow(request: str, operations: list[RhinoOperationInput] | None = None, active_host: str = "rhino", idempotency_key: str = "", dry_run: bool = False, assertions: dict | None = None, project_id: str = "default", model: dict | None = None, token_usage: dict | None = None, budget: dict | None = None, correlation_id: str | None = None) -> dict:
    """Run focused query, one typed mutation, independent verification, memory promotion, and trace recording as one deterministic workflow."""
    limits = ExecutionBudget.from_mapping(budget)
    result = await _workflow.run(request=request, operations=dump_operations(operations), active_host=active_host, idempotency_key=idempotency_key, dry_run=dry_run, assertions=assertions, project_id=project_id, model=model, token_usage=token_usage, budget=limits, correlation_id=correlation_id)
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
async def rhino_export_scene(path: str, expected_units: str = "Meters") -> dict:
    """Export the active Rhino document to a new absolute .glb (preferred) or .fbx path, refusing overwrite and unit mismatch."""
    return await _rhino_direct.export_scene(path, expected_units=expected_units)


@mcp.tool()
async def rhino_open_working_document(path: str) -> dict:
    """Open an existing absolute .3dm working copy after restart; MASTER/HERO files and unsaved replacement are refused."""
    return await _rhino_direct.open_working_document(path)


@mcp.tool()
async def blender_apply_operations(intent: str, operations: list[BlenderOperationInput], idempotency_key: str, dry_run: bool = False) -> dict:
    """Apply exact typed Blender operations. Prefer blender_render_archviz for the standard demo render."""
    return await _blender.execute(intent=intent, operations=dump_blender_operations(operations), idempotency_key=idempotency_key, dry_run=dry_run)


@mcp.tool()
async def blender_render_archviz(
    output_path: str,
    blend_path: str,
    idempotency_key: str,
    camera_location: tuple[float, float, float] = (28.0, -32.0, 22.0),
    camera_target: tuple[float, float, float] = (5.0, -2.0, 3.0),
    lens_mm: float = 48.0,
    resolution: tuple[int, int] = (768, 512),
    samples: int = 32,
    lighting_preset: Literal["daylight", "golden_hour", "studio"] = "daylight",
) -> dict:
    """Render with a managed HDRI preset: daylight for clear architectural review, golden_hour for warm evening requests, or studio for neutral material inspection."""
    output = Path(output_path)
    blend = Path(blend_path)
    if not output.is_absolute() or output.suffix.lower() != ".png":
        raise ValueError("output_path must be an absolute .png path")
    if not blend.is_absolute() or blend.suffix.lower() != ".blend":
        raise ValueError("blend_path must be an absolute .blend path")
    if output.exists() and not _blender.has_receipt(idempotency_key):
        raise ValueError("output_path already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    blend.parent.mkdir(parents=True, exist_ok=True)
    hdri_path, lighting = _managed_hdri_path(lighting_preset)
    return await _blender.execute(
        intent=f"Create and render a verified architectural hero view with the managed {lighting_preset} HDRI preset",
        operations=[
            {"op": "set_world_hdri", "id": "world_hdri", "path": str(hdri_path), "strength": lighting["strength"], "rotation_degrees": lighting["rotation_degrees"]},
            {"op": "create_camera", "id": "hero_camera", "name": "AEC Hero Camera", "location": camera_location, "target": camera_target, "lens_mm": lens_mm},
            {"op": "create_light", "id": "sun", "name": "AEC Sun", "type": "SUN", "location": (0, 0, 30), "rotation_degrees": lighting["sun_rotation"], "energy": lighting["sun_energy"]},
            {"op": "create_light", "id": "fill", "name": "AEC Fill", "type": "AREA", "location": (8, -12, 20), "rotation_degrees": (20, 0, 25), "energy": lighting["fill_energy"]},
            {"op": "render_settings", "id": "settings", "engine": "BLENDER_EEVEE_NEXT", "resolution": resolution, "samples": samples},
            {"op": "render", "id": "render", "path": str(output)},
            {"op": "save_blend", "id": "save", "path": str(blend)},
            {"op": "present_scene", "id": "present"},
        ],
        idempotency_key=idempotency_key,
    )


@mcp.tool()
async def blender_import_handoff(
    export_path: str,
    blend_path: str,
    idempotency_key: str,
    collection: str = "Rhino Handoff",
    unit_scale: float = 1.0,
) -> dict:
    """Import one Rhino GLB, save the working .blend, frame it, and foreground the exact connected Blender instance."""
    source = Path(export_path)
    destination = Path(blend_path)
    if not source.is_absolute() or not source.is_file() or source.suffix.lower() != ".glb":
        raise ValueError("export_path must be an existing absolute .glb path")
    if not destination.is_absolute() or destination.suffix.lower() != ".blend":
        raise ValueError("blend_path must be an absolute .blend path")
    if destination.exists() and not _blender.has_receipt(idempotency_key):
        raise ValueError("blend_path already exists")
    if any(word in destination.name.upper() for word in ("MASTER", "HERO")):
        raise ValueError("blend_path must be a working file, not MASTER or HERO")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return await _blender.execute(
        intent="Import the verified Rhino handoff, persist it, and visibly present the working scene",
        operations=[
            {"op": "import_scene", "id": "import_handoff", "path": str(source), "collection": collection, "source_host": "rhino", "unit_scale": unit_scale},
            {"op": "save_blend", "id": "save_working_scene", "path": str(destination)},
            {"op": "present_scene", "id": "present_working_scene"},
        ],
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def blender_validate_handoff(manifest: dict) -> dict:
    """Validate Rhino-to-Blender object IDs, units, layers, and export path before import."""
    return validate_handoff_manifest(manifest)


@mcp.tool()
def blender_proof_and_recovery(receipt: dict) -> dict:
    """Return the deterministic verify/reconcile/rollback plan for a Blender receipt."""
    return blender_recovery_plan(receipt)


@mcp.tool()
async def comfyui_health() -> dict:
    """Verify that the managed loopback ComfyUI service and GPU backend are ready."""
    return await _comfyui.health()


@mcp.tool()
async def comfyui_stylize_image(
    input_path: str,
    output_path: str,
    prompt: str,
    idempotency_key: str,
    negative_prompt: str = "distorted architecture, changed geometry, people, text, watermark, blurry, low quality",
    seed: int = 0,
    steps: int = 20,
    width: int = 768,
    height: int = 512,
) -> dict:
    """Run the installed Flux 2 Klein image-edit workflow and atomically retrieve one PNG result."""
    return await _comfyui.stylize(
        input_path=input_path, output_path=output_path, prompt=prompt,
        idempotency_key=idempotency_key, negative_prompt=negative_prompt,
        seed=seed, steps=steps, width=width, height=height,
    )


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
async def rhino_viewport_state() -> dict:
    """Return the active Rhino viewport name, camera, target, up vector, lens, and projection."""
    return await _rhino_direct.viewport_command("viewport_get_state")


@mcp.tool()
async def rhino_viewport_zoom_extents() -> dict:
    """Visibly zoom the active Rhino viewport to the extents of document geometry and return the resulting camera state."""
    return await _rhino_direct.viewport_command("viewport_zoom_extents")


@mcp.tool()
async def rhino_viewport_set_camera(camera: tuple[float, float, float], target: tuple[float, float, float] | None = None, lens_mm: float | None = None) -> dict:
    """Visibly set the active Rhino camera location, optional target, and optional 35mm lens length."""
    params: dict = {"camera": list(camera)}
    if target is not None: params["target"] = list(target)
    if lens_mm is not None: params["lens_mm"] = lens_mm
    return await _rhino_direct.viewport_command("viewport_set_camera", params)


@mcp.tool()
async def rhino_viewport_set_target(target: tuple[float, float, float]) -> dict:
    """Visibly aim the active Rhino camera at an exact model-space target while preserving its location."""
    return await _rhino_direct.viewport_command("viewport_set_target", {"target": list(target)})


@mcp.tool()
async def rhino_viewport_orbit(azimuth_degrees: float = 0.0, elevation_degrees: float = 0.0, target: tuple[float, float, float] | None = None) -> dict:
    """Visibly orbit the active Rhino camera around its target (or an explicit model-space target) and return the resulting state."""
    params: dict = {"azimuth_degrees": azimuth_degrees, "elevation_degrees": elevation_degrees}
    if target is not None: params["target"] = list(target)
    return await _rhino_direct.viewport_command("viewport_orbit", params)


@mcp.tool()
async def rhino_viewport_restore_named_view(name: str) -> dict:
    """Visibly restore an existing Rhino named view into the active viewport."""
    return await _rhino_direct.viewport_command("viewport_restore_named_view", {"name": name})


@mcp.tool()
async def rhino_viewport_capture(viewport: str = "active", width: int = 1024, height: int = 768, zoom_to_fit: bool = False) -> Image:
    """Capture a Rhino viewport as a PNG image for visual inspection. Capture itself does not move the persistent camera."""
    result = await _rhino_direct.viewport_command("capture_viewport", {
        "viewport": viewport, "width": width, "height": height,
        "show_grid": False, "show_axes": False, "show_cplane_axes": False,
        "zoom_to_fit": zoom_to_fit,
    })
    return Image(data=base64.b64decode(result["image_data"], validate=True), format="png")


@mcp.tool()
async def rhino_scene_query(query: RhinoSceneQuery | None = None, audit_limit: int = 2000) -> dict:
    """Read Rhino through a bounded typed selector. Start with mode=summary. Object mode returns at most 100 compact records; geometry is omitted unless explicitly requested."""
    selector = normalize_scene_query(query)
    scene = await _rhino_direct.scene_index(max_objects=audit_limit)
    objects = scene.get("objects", [])
    raw_document = scene.get("document") or {}
    raw_summary = raw_document.get("summary") or {}
    document = {key: raw_document.get(key) for key in (
        "name", "path", "units", "tolerance", "angle_tolerance", "date_modified"
    ) if raw_document.get(key) is not None}
    layer_counts = Counter(str(item.get("layer") or "") for item in objects)
    type_counts = Counter(str(item.get("type", item.get("kind", "UNKNOWN"))) for item in objects)
    base = {
        "schema_version": scene.get("schema_version"),
        "host": "rhino",
        "document_id": scene.get("document_id"),
        "document_revision": scene.get("document_revision"),
        "document": document,
        "bounds": raw_summary.get("model_bounding_box"),
        "total_objects": raw_summary.get("object_count", len(objects)),
        "indexed_objects": len(objects),
        "truncated": bool(scene.get("truncated")),
        "cache_hit": bool(scene.get("cache_hit")),
    }
    if selector.mode == "summary":
        return {**base, "mode": "summary", "layer_counts": dict(layer_counts.most_common()),
                "type_counts": dict(type_counts.most_common())}
    if selector.mode == "layers":
        return {**base, "mode": "layers", "layers": [
            {"name": name, "object_count": count} for name, count in layer_counts.most_common()
        ]}
    ids = set(selector.ids) if selector.ids else None
    name = (selector.name or "").casefold()
    layer = (selector.layer or "").casefold()
    kind = (selector.kind or "").casefold()
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
        compact = {key: item.get(key) for key in (
            "id", "name", "type", "layer", "bounding_box", "color", "material", "content_hash"
        )}
        if selector.include_geometry:
            compact["geometry"] = item.get("geometry")
            compact["attributes"] = item.get("attributes")
        selected.append(compact)
        if len(selected) >= selector.limit:
            break
    return {**base, "mode": "objects", "objects": selected, "count": len(selected),
            "selector": selector.model_dump(exclude_none=True)}


@mcp.tool()
async def rhino_apply_operations(
    intent: str,
    operations: list[RhinoOperationInput],
    idempotency_key: str,
    document_revision: str,
    dry_run: bool = False,
    checkpoint_path: str | None = None,
) -> dict:
    """Execute one typed Rhino batch. Creation ops contain geometry only. To label or layer a new object, give it an id then add set_attributes targeting $id; never send an attributes field on create ops."""
    normalized_operations = dump_operations(operations)
    receipt = await _rhino_direct.execute_operations(
        intent=intent,
        operations=normalized_operations,
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
        "normalized_transaction": {"operations": normalized_operations},
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
