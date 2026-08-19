import asyncio

from hermes_aec_runtime.mcp_server import mcp
import hermes_aec_runtime.mcp_server as server


def test_fast_path_and_all_typed_hosts_are_exposed():
    tools = {item.name for item in asyncio.run(mcp.list_tools())}
    assert {"aec_workflow_plan", "aec_run_workflow", "aec_runtime_health"} <= tools
    for host in ("rhino", "blender", "freecad"):
        assert f"{host}_scene_query" in tools
        assert f"{host}_apply_operations" in tools
    assert {"blender_import_handoff", "blender_render_archviz", "comfyui_health", "comfyui_stylize_image"} <= tools


def test_archviz_render_tool_assembles_one_known_good_transaction(tmp_path, monkeypatch):
    class FakeBlender:
        def has_receipt(self, key):
            return False

        async def execute(self, **values):
            self.values = values
            return {"status": "completed", "transaction_id": "render-1"}

    fake = FakeBlender()
    monkeypatch.setattr(server, "_blender", fake)
    output = tmp_path / "hero.png"
    blend = tmp_path / "working.blend"
    result = asyncio.run(server.blender_render_archviz(
        str(output), str(blend), "render-key", camera_location=(20, -20, 15), camera_target=(5, 0, 3),
    ))
    assert result["status"] == "completed"
    assert fake.values["idempotency_key"] == "render-key"
    operations = fake.values["operations"]
    assert [item["op"] for item in operations] == [
        "create_camera", "create_light", "create_light", "render_settings", "render", "save_blend", "present_scene",
    ]
    assert operations[0]["target"] == (5, 0, 3)
