import pytest

from hermes_aec_runtime.blender_operations import (
    BlenderOperationError, compile_blender_transaction, normalize_blender_operations,
)


def test_compiles_complete_visualization_batch():
    ops = [
        {"op": "import_scene", "path": "house.glb", "collection": "Rhino Handoff", "source_host": "rhino", "unit_scale": 1.0},
        {"op": "ensure_collection", "name": "Presentation"},
        {"op": "transform", "objects": ["House"], "location": [1, 2, 3], "rotation_degrees": [0, 0, 90]},
        {"op": "assign_material", "objects": ["House"], "material": "Concrete", "base_color": [.5, .5, .5, 1]},
        {"op": "create_camera", "name": "Hero", "location": [10, -10, 8], "lens_mm": 35},
        {"op": "create_light", "name": "Sun", "type": "SUN", "energy": 4},
        {"op": "render_settings", "engine": "BLENDER_EEVEE_NEXT", "resolution": [1280, 720], "samples": 32},
        {"op": "save_blend", "path": "presentation.blend"},
        {"op": "render", "path": "hero.png"},
        {"op": "present_scene"},
    ]
    compiled = compile_blender_transaction(ops)
    assert compiled.normalized["host"] == "blender"
    assert len(compiled.normalized["operations"]) == 10
    assert "bpy.ops.render.render(write_still=True)" in compiled.script
    assert "__presented_scene__" in compiled.script
    assert len(compiled.fingerprint) == 64


def test_import_accepts_validated_handoff_scale_alias_and_applies_it_to_new_objects():
    compiled = compile_blender_transaction([{
        "op": "import_scene", "path": "house.glb", "source_host": "rhino",
        "unit_scale_to_meters": 0.001,
    }])
    operation = compiled.normalized["operations"][0]
    assert operation["source_host"] == "rhino"
    assert operation["unit_scale"] == 0.001
    assert "component*op[\"unit_scale\"]" in compiled.script


def test_eevee_engine_is_selected_across_blender_versions():
    compiled = compile_blender_transaction([{"op": "render_settings", "engine": "BLENDER_EEVEE_NEXT"}])
    assert '"BLENDER_EEVEE_NEXT":"BLENDER_EEVEE"' in compiled.script
    assert '"BLENDER_EEVEE":"BLENDER_EEVEE_NEXT"' in compiled.script
    assert "except TypeError" in compiled.script
    assert normalize_blender_operations([{"op": "render_settings", "engine": "BLENDER_EEVEE"}])[0]["engine"] == "BLENDER_EEVEE"


@pytest.mark.parametrize("operation", [
    {"op": "import_scene", "path": "bad.3dm"},
    {"op": "transform", "objects": [] , "location": [0, 0, 0]},
    {"op": "assign_material", "objects": ["A"], "material": "M", "base_color": [2, 0, 0, 1]},
    {"op": "create_light", "name": "L", "type": "LASER"},
    {"op": "render", "path": "out.txt"},
    {"op": "import_scene", "path": "house.glb", "source_host": "freecad"},
    {"op": "import_scene", "path": "house.glb", "unit_scale": 0},
    {"op": "import_scene", "path": "house.glb", "unit_scale": 1, "unit_scale_to_meters": 1},
])
def test_rejects_unsafe_or_invalid_operations(operation):
    with pytest.raises(BlenderOperationError):
        normalize_blender_operations([operation])


def test_normalization_and_fingerprint_are_deterministic():
    op = [{"op": "ensure_collection", "name": "AEC"}]
    assert compile_blender_transaction(op).fingerprint == compile_blender_transaction(op).fingerprint
