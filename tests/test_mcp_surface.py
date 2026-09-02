import asyncio

from hermes_aec_runtime.mcp_server import mcp
import hermes_aec_runtime.mcp_server as server


def test_fast_path_and_all_typed_hosts_are_exposed():
    tools = {item.name for item in asyncio.run(mcp.list_tools())}
    assert {"aec_workflow_plan", "aec_run_workflow", "aec_runtime_health"} <= tools
    for host in ("rhino", "blender", "freecad"):
        assert f"{host}_scene_query" in tools
        assert f"{host}_apply_operations" in tools
    assert {"blender_import_handoff", "blender_list_hdri_files", "blender_render_archviz", "comfyui_health", "comfyui_stylize_image"} <= tools


def test_hdri_listing_reports_managed_and_additional_files(tmp_path, monkeypatch):
    (tmp_path / "quadrangle_cloudy_2k.hdr").write_bytes(b"daylight")
    (tmp_path / "custom_environment.exr").write_bytes(b"custom")
    monkeypatch.setenv("HERMES_AEC_HDRI_ROOT", str(tmp_path))

    result = server.blender_list_hdri_files()

    assert result["library_available"] is True
    assert result["license"] == "CC0-1.0"
    assert [item["preset"] for item in result["presets"]] == ["daylight", "golden_hour", "studio"]
    assert result["presets"][0]["display_name"] == "Quadrangle Cloudy"
    assert result["presets"][0]["available"] is True
    assert result["presets"][1]["available"] is False
    assert [item["filename"] for item in result["additional_files"]] == ["custom_environment.exr"]


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
    hdri_root = tmp_path / "hdri"
    hdri_root.mkdir()
    (hdri_root / "quadrangle_cloudy_2k.hdr").write_bytes(b"test-hdri")
    monkeypatch.setenv("HERMES_AEC_HDRI_ROOT", str(hdri_root))
    result = asyncio.run(server.blender_render_archviz(
        str(output), str(blend), "render-key", camera_source="explicit", camera_location=(20, -20, 15), camera_target=(5, 0, 3),
    ))
    assert result["status"] == "completed"
    assert fake.values["idempotency_key"] == "render-key"
    operations = fake.values["operations"]
    assert [item["op"] for item in operations] == [
        "set_world_hdri", "create_camera", "create_light", "create_light", "render_settings", "render", "save_blend", "present_scene",
    ]
    assert operations[0]["path"].endswith("quadrangle_cloudy_2k.hdr")
    assert operations[1]["target"] == (5, 0, 3)
    assert operations[-1]["frame_all"] is False


def test_archviz_render_uses_current_blender_viewport_by_default(tmp_path, monkeypatch):
    class FakeBlender:
        def has_receipt(self, key):
            return False

        async def execute(self, **values):
            self.values = values
            return {"status": "completed"}

    fake = FakeBlender()
    monkeypatch.setattr(server, "_blender", fake)
    hdri_root = tmp_path / "hdri"
    hdri_root.mkdir()
    (hdri_root / "quadrangle_cloudy_2k.hdr").write_bytes(b"test-hdri")
    monkeypatch.setenv("HERMES_AEC_HDRI_ROOT", str(hdri_root))

    asyncio.run(server.blender_render_archviz(
        str(tmp_path / "viewport.png"), str(tmp_path / "viewport.blend"), "viewport-key",
    ))

    camera = fake.values["operations"][1]
    assert camera == {"op": "create_camera_from_viewport", "id": "hero_camera", "name": "AEC Viewport Camera"}
    assert "viewport camera" in fake.values["intent"]


def test_archviz_explicit_camera_requires_both_vectors(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_AEC_HDRI_ROOT", str(tmp_path))
    (tmp_path / "quadrangle_cloudy_2k.hdr").write_bytes(b"test-hdri")
    try:
        asyncio.run(server.blender_render_archviz(
            str(tmp_path / "bad.png"), str(tmp_path / "bad.blend"), "bad-key",
            camera_source="explicit", camera_location=(1, 2, 3),
        ))
    except ValueError as exc:
        assert "requires camera_location and camera_target" in str(exc)
    else:
        raise AssertionError("incomplete explicit camera must fail")


def test_archviz_render_selects_managed_golden_hour_preset(tmp_path, monkeypatch):
    class FakeBlender:
        def has_receipt(self, key):
            return False

        async def execute(self, **values):
            self.values = values
            return {"status": "completed"}

    fake = FakeBlender()
    monkeypatch.setattr(server, "_blender", fake)
    hdri_root = tmp_path / "hdri"
    hdri_root.mkdir()
    (hdri_root / "safari_sunset_2k.hdr").write_bytes(b"test-hdri")
    monkeypatch.setenv("HERMES_AEC_HDRI_ROOT", str(hdri_root))
    asyncio.run(server.blender_render_archviz(
        str(tmp_path / "golden.png"), str(tmp_path / "golden.blend"), "golden-key", lighting_preset="golden_hour",
    ))
    assert fake.values["operations"][0]["path"].endswith("safari_sunset_2k.hdr")
    assert "golden_hour" in fake.values["intent"]
