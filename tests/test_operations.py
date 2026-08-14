import json

import pytest

from hermes_aec_runtime.operations import OperationValidationError, compile_transaction, normalize_operations


def test_compiles_batch_with_aliases_and_deterministic_fingerprint():
    operations = [
        {"op": "create_box", "id": "body", "min": [0, 0, 0], "max": [2, 3, 4]},
        {"op": "transform_in_place", "targets": ["$body"], "translation": [5, 0, 0]},
        {"op": "set_attributes", "targets": ["$body"], "name": "East Mass", "layer": "AEC::Massing", "color": [10, 20, 30]},
    ]
    first = compile_transaction(operations)
    second = compile_transaction(operations)
    assert first.fingerprint == second.fingerprint
    assert first.normalized["operations"][1]["id"] == "op_2"
    assert "doc.Objects.Transform(object_id, xform, False)" in first.script
    assert "East Mass" in first.script
    assert first.expected_change.startswith("typed batch:")


@pytest.mark.parametrize("operation, message", [
    ({"op": "create_sphere", "center": [0, 0, 0], "radius": 0}, "greater than zero"),
    ({"op": "create_box", "min": [0, 0, 0], "max": [0, 2, 3]}, "max must exceed min"),
    ({"op": "create_line", "start": [1, 1, 1], "end": [1, 1, 1]}, "endpoints must differ"),
    ({"op": "delete", "targets": ["$future"]}, "unknown or future"),
    ({"op": "delete", "targets": ["not-a-guid"]}, "valid GUID"),
    ({"op": "create_point", "point": [0, float("nan"), 0]}, "finite number"),
    ({"op": "create_point", "point": [0, 0, 0], "surprise": True}, "unknown fields"),
])
def test_rejects_invalid_input(operation, message):
    with pytest.raises(OperationValidationError, match=message):
        normalize_operations([operation])


def test_supports_full_operation_surface():
    guid_a = "11111111-1111-1111-1111-111111111111"
    guid_b = "22222222-2222-2222-2222-222222222222"
    operations = [
        {"op": "create_point", "point": [0, 0, 0]},
        {"op": "create_line", "id": "line", "start": [0, 0, 0], "end": [2, 0, 0]},
        {"op": "create_polyline", "id": "outline", "points": [[0, 0, 0], [1, 0, 0], [1, 1, 0]], "closed": True},
        {"op": "create_sphere", "center": [0, 0, 0], "radius": 2},
        {"op": "duplicate", "targets": ["$outline"], "translation": [3, 0, 0]},
        {"op": "extrude_curve", "targets": ["$outline"], "vector": [0, 0, 3], "cap": True},
        {"op": "offset_curve", "targets": ["$outline"], "distance": 0.2},
        {"op": "boolean_union", "targets": [guid_a, guid_b], "delete_input": False},
        {"op": "boolean_difference", "targets": [guid_a], "cutters": [guid_b]},
        {"op": "boolean_intersection", "targets": [guid_a, guid_b]},
        {"op": "delete", "targets": ["$line"]},
    ]
    compiled = compile_transaction(operations)
    assert len(compiled.normalized["operations"]) == len(operations)
    embedded = compiled.script.split("ops = json.loads(", 1)[1].split(")\n", 1)[0]
    assert json.loads(eval(embedded))[-1]["op"] == "delete"


def test_requires_exactly_one_transform_mode():
    with pytest.raises(OperationValidationError, match="exactly one"):
        normalize_operations([{"op": "transform_in_place", "targets": ["11111111-1111-1111-1111-111111111111"], "translation": [1, 0, 0], "scale": 2}])


def test_material_and_rotation_are_normalized():
    result = normalize_operations([
        {"op": "set_attributes", "targets": ["11111111-1111-1111-1111-111111111111"], "material_index": 4},
        {"op": "transform_in_place", "targets": ["11111111-1111-1111-1111-111111111111"], "rotation": {"axis": [0, 0, 1], "degrees": 90}, "center": [1, 2, 0]},
    ])
    assert result[0]["material_index"] == 4
    assert result[1]["rotation"]["degrees"] == 90.0
