import json

import pytest

from hermes_aec_runtime.scene_index import (
    AUDIT_MARKER,
    SCENE_SCHEMA_VERSION,
    Bounds,
    SceneIndex,
    SceneIndexError,
    build_rhino_audit_script,
    parse_rhino_audit_output,
)


def scene() -> SceneIndex:
    return SceneIndex({
        "schema_version": SCENE_SCHEMA_VERSION,
        "document_revision": "12:3:99",
        "units": "Meters",
        "tolerance": 0.001,
        "bounds": {"min": [0, 0, 0], "max": [21, 21, 4]},
        "layers": ["AEC::Walls", "AEC::Site"],
        "objects": [
            {"id": "a", "name": "North Wall", "kind": "Brep", "layer": "AEC::Walls", "visible": True, "locked": False, "bounds": {"min": [0, 0, 0], "max": [10, 1, 3]}},
            {"id": "b", "name": "Pool", "kind": "Brep", "layer": "AEC::Site", "visible": True, "locked": True, "bounds": {"min": [12, 12, 0], "max": [20, 20, 1]}},
            {"id": "c", "name": "Fence", "kind": "Curve", "layer": "AEC::Site", "visible": False, "locked": False, "bounds": {"min": [11, 11, 0], "max": [21, 21, 2]}},
        ],
        "relationships": [
            {"type": "on_layer", "source": "b", "target": "layer:AEC::Site"},
            {"type": "in_group", "source": "c", "target": "group:7"},
        ],
    })


def test_parse_marker_and_contract():
    payload = scene().payload
    parsed = parse_rhino_audit_output("diagnostic\n" + AUDIT_MARKER + json.dumps(payload))
    assert parsed.document_revision == "12:3:99"
    assert parsed.payload["units"] == "Meters"


def test_filters_and_wildcards_are_compact_and_focused():
    index = scene()
    assert [o["id"] for o in index.query(name="North*")] == ["a"]
    assert [o["id"] for o in index.query(layer="aec::site", kind="Brep", locked=True)] == ["b"]
    assert [o["id"] for o in index.query(visible=False)] == ["c"]
    assert [o["id"] for o in index.query(related_to="layer:AEC::Site")] == ["b"]


def test_spatial_selectors_use_object_bounds():
    index = scene()
    zone = Bounds((10, 10, -1), (22, 22, 3))
    assert [o["id"] for o in index.query(inside=zone)] == ["b", "c"]
    assert [o["id"] for o in index.query(intersects={"min": [19, 19, 0], "max": [22, 22, 3]})] == ["b", "c"]
    assert [o["id"] for o in index.query(near=[16, 16, 0], radius=6)] == ["b", "c"]


def test_bad_contract_and_selector_fail_clearly():
    with pytest.raises(SceneIndexError, match="missing"):
        SceneIndex({"schema_version": SCENE_SCHEMA_VERSION})
    with pytest.raises(SceneIndexError, match="near requires radius"):
        scene().query(near=[0, 0, 0])
    with pytest.raises(SceneIndexError, match="marker"):
        parse_rhino_audit_output("ordinary Rhino output")


def test_audit_script_is_bounded_read_only_and_emits_contract():
    script = build_rhino_audit_script(limit=321)
    assert "limit = 321" in script
    assert AUDIT_MARKER in script
    assert SCENE_SCHEMA_VERSION in script
    assert "doc.Objects.Add" not in script
    assert '"relationships"' in script
    with pytest.raises(ValueError):
        build_rhino_audit_script(limit=10001)
