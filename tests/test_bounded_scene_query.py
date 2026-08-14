import asyncio

import hermes_aec_runtime.mcp_server as server
from hermes_aec_runtime.rhinomcp_transport import RhinoMCPGateway
from test_rhinomcp_transport import FakeTransport


class FakeSceneGateway:
    calls = 0

    async def scene_index(self, **_):
        type(self).calls += 1
        return {
            "schema_version": "1.0", "document_id": "house", "document_revision": "rev-1",
            "document": {"units": "Meters"}, "bounds": [[0, 0, 0], [10, 10, 10]],
            "total_objects": 3, "objects": [
                {"id": "1", "name": "Pool", "type": "BREP", "layer": "SITE", "geometry": {"huge": "x" * 1000}},
                {"id": "2", "name": "Rail", "type": "CURVE", "layer": "SAFETY", "geometry": {"huge": "x" * 1000}},
                {"id": "3", "name": "Deck", "type": "BREP", "layer": "SITE", "geometry": {"huge": "x" * 1000}},
            ],
        }


def test_default_scene_read_is_summary_not_object_dump(monkeypatch):
    monkeypatch.setattr(server, "_rhino_direct", FakeSceneGateway())
    result = asyncio.run(server.rhino_scene_query())
    assert result["mode"] == "summary"
    assert "objects" not in result
    assert result["layer_counts"] == {"SITE": 2, "SAFETY": 1}


def test_object_read_is_filtered_bounded_and_compact(monkeypatch):
    monkeypatch.setattr(server, "_rhino_direct", FakeSceneGateway())
    result = asyncio.run(server.rhino_scene_query({"mode": "objects", "layer": "site", "limit": 1}))
    assert result["count"] == 1
    assert result["objects"][0]["name"] == "Pool"
    assert "geometry" not in result["objects"][0]


def test_gateway_reuses_scene_and_invalidates_cache_after_write():
    fake = FakeTransport()
    fake.objects = [{"id": "11111111-1111-1111-1111-111111111111", "type": "POINT"}]
    gateway = RhinoMCPGateway(fake)
    first = asyncio.run(gateway.scene_index())
    second = asyncio.run(gateway.scene_index())
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert len([call for call in fake.calls if call[0] == "get_document_summary"]) == 1


def test_completed_receipt_contains_automatic_verification():
    fake = FakeTransport(); gateway = RhinoMCPGateway(fake)
    receipt = asyncio.run(gateway.execute_operations(
        intent="point", operations=[{"op": "create_point", "point": [0, 0, 0]}],
        dry_run=False, idempotency_key="auto-verify",
    ))
    assert receipt["verification"]["status"] == "verified"
    assert receipt["verification"]["independent_scene_delta"] is True
