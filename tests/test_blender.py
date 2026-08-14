import asyncio

from hermes_aec_runtime.blender import BlenderGateway, recovery_plan, validate_handoff_manifest


class FakeTransport:
    def __init__(self, state): self.state = state
    async def call(self, tool, arguments):
        self.state["calls"].append((tool, arguments))
        if self.state.get("failures", 0):
            self.state["failures"] -= 1
            raise ConnectionError("injected disconnect")
        if tool == "get_scene_info":
            return {"document_id": "blend-1", "units": "meters", "objects": [{"id": "a", "name": "House", "type": "MESH", "collection": "AEC", "location": [0, 0, 0]}]}
        return {"stdout": '{"status":"completed","changed":["House"]}'}


def gateway(state): return BlenderGateway(lambda: FakeTransport(state), read_attempts=3)


def test_scene_preprocessing_matches_runtime_shape_and_retries_reads():
    state = {"calls": [], "failures": 2}
    scene = asyncio.run(gateway(state).scene_preprocessing())
    assert scene["host"] == "blender"
    item = scene["objects"][0]
    assert {key:item[key] for key in ("id","name","kind","layer","properties")} == {"id": "a", "name": "House", "kind": "MESH", "layer": "AEC", "properties": {"location": [0, 0, 0]}}
    assert len(item["content_hash"]) == 64
    assert len(scene["document_revision"]) == 64
    assert len(state["calls"]) == 3


def test_mutation_receipt_is_idempotent_and_payload_bound():
    state = {"calls": []}; client = gateway(state)
    kwargs = {"intent": "organize", "operations": [{"op": "ensure_collection", "name": "AEC"}], "idempotency_key": "demo-1"}
    first = asyncio.run(client.execute(**kwargs)); second = asyncio.run(client.execute(**kwargs))
    assert first["status"] == "completed" and second["replayed"] is True
    assert len(state["calls"]) == 1
    blocked = asyncio.run(client.execute(intent="other", operations=[{"op": "ensure_collection", "name": "Other"}], idempotency_key="demo-1"))
    assert blocked["status"] == "blocked"


def test_mutation_disconnect_is_unknown_and_not_retried():
    state = {"calls": [], "failures": 1}
    client = gateway(state)
    kwargs = dict(intent="save", operations=[{"op": "save_blend", "path": "a.blend"}], idempotency_key="save-1")
    result = asyncio.run(client.execute(**kwargs))
    replay = asyncio.run(client.execute(**kwargs))
    assert result["status"] == "unknown"
    assert replay["replayed"] is True
    assert len(state["calls"]) == 1


def test_dry_run_does_not_touch_transport():
    state = {"calls": []}
    result = asyncio.run(gateway(state).execute(intent="render", operations=[{"op": "render", "path": "a.png"}], idempotency_key="r-1", dry_run=True))
    assert result["status"] == "validated" and not state["calls"]


def test_handoff_manifest_requires_ids_layers_units_and_export():
    valid = validate_handoff_manifest({"schema_version": "1.0", "source_host": "rhino", "units": "millimeters", "export_path": "house.glb", "objects": [{"rhino_id": "guid-1", "layer": "Walls"}]})
    assert valid == {"valid": True, "errors": [], "object_count": 1, "unit_scale_to_meters": .001}
    invalid = validate_handoff_manifest({"schema_version": "0", "objects": [{"rhino_id": "x", "layer": ""}, {"rhino_id": "x", "layer": "A"}]})
    assert not invalid["valid"] and any("duplicated" in error for error in invalid["errors"])


def test_recovery_is_conservative():
    assert recovery_plan({"status": "unknown"})["action"] == "reconcile"
    assert recovery_plan({"status": "failed"})["action"] == "rollback"
    assert recovery_plan({"status": "completed"})["action"] == "verify"
