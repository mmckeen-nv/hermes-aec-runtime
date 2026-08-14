import pytest

from hermes_aec_runtime.rhinomcp_mapping import (
    RhinoMCPMappingError, compile_rhinomcp_commands, scene_from_rhinomcp,
)


def test_maps_primitives_with_correct_rhinomcp_origins():
    commands = compile_rhinomcp_commands([
        {"op": "create_box", "id": "box", "min": [2, 4, 6], "max": [6, 10, 14]},
        {"op": "create_sphere", "id": "ball", "center": [3, 4, 5], "radius": 2},
        {"op": "set_attributes", "targets": ["$box"], "name": "Mass", "layer": "AEC", "color": [1, 2, 3]},
    ])
    assert commands[0].params == {"type": "BOX", "params": {"width": 4.0, "length": 6.0, "height": 8.0}, "translation": [4.0, 7.0, 10.0]}
    assert commands[1].params["translation"] == [3.0, 4.0, 5.0]
    assert commands[2].params == {"id": "$box", "layer": "AEC", "color": [1, 2, 3], "new_name": "Mass"}


def test_closed_polyline_is_closed_explicitly_for_plugin():
    command = compile_rhinomcp_commands([{"op": "create_polyline", "id": "p", "points": [[0, 0, 0], [1, 0, 0], [1, 1, 0]], "closed": True}])[0]
    assert command.params["params"]["points"][0] == command.params["params"]["points"][-1]


def test_maps_hardened_stable_transform_and_duplicate_commands():
    target = "11111111-1111-1111-1111-111111111111"
    commands = compile_rhinomcp_commands([
        {"op": "transform_in_place", "id": "turned", "targets": [target],
         "rotation": {"axis": [0, 0, 1], "degrees": 90}, "center": [1, 2, 0]},
        {"op": "duplicate", "id": "copy", "targets": ["$turned"], "translation": [5, 0, 0]},
    ])
    assert commands[0].command == "transform_object_in_place"
    assert commands[0].params == {
        "id": target, "rotation_axis": [0.0, 0.0, 1.0],
        "rotation_degrees": 90.0, "center": [1.0, 2.0, 0.0],
    }
    assert commands[1].command == "duplicate_object"
    assert commands[1].params == {"id": "$turned", "translation": [5.0, 0.0, 0.0]}


def test_normalizes_scene_and_produces_stable_revision():
    summary = {"meta_data": {"name": "House", "path": "C:/House.3dm", "units": "Meters"}, "object_count": 1}
    objects = [{"id": "a", "name": "Wall", "type": "BREP", "layer": "Walls", "color": {"r": 1}, "bounding_box": [[0, 0, 0], [1, 1, 1]]}]
    first = scene_from_rhinomcp(summary, objects)
    second = scene_from_rhinomcp(summary, objects)
    assert first["document_revision"] == second["document_revision"]
    assert first["document_id"] == "C:/House.3dm" and first["objects"][0]["content_hash"]
