import asyncio

import hermes_aec_runtime.mcp_server as server


class FakeRhino:
    executed = 0

    async def document_revision(self):
        return "doc:10:99"

    async def execute_python(self, **kwargs):
        type(self).executed += 1
        return {"status": "completed", "transaction_id": "tx", "created_ids": ["new"], "deleted_ids": []}

    async def save_checkpoint(self, path):
        return {"saved": path}


class FakeDirect:
    executed = 0

    async def execute_operations(self, **kwargs):
        if kwargs["document_revision"] != "doc:10:99":
            return {"status": "blocked", "fingerprint": "fp"}
        type(self).executed += 1
        return {
            "status": "completed", "transaction_id": "tx", "fingerprint": "fp",
            "created_ids": ["new"], "modified_ids": [], "deleted_ids": [],
        }


def test_typed_surface_blocks_stale_document_revision(monkeypatch):
    FakeDirect.executed = 0
    monkeypatch.setattr(server, "_rhino_direct", FakeDirect())
    result = asyncio.run(server.rhino_apply_operations(
        intent="create point",
        operations=[{"op": "create_point", "point": [0, 0, 0]}],
        idempotency_key="stale-test",
        document_revision="old:revision",
    ))
    assert result["status"] == "blocked"
    assert FakeDirect.executed == 0


def test_typed_surface_executes_and_checkpoints_valid_revision(monkeypatch):
    FakeDirect.executed = 0
    monkeypatch.setattr(server, "_rhino_direct", FakeDirect())
    monkeypatch.setattr(server, "RhinoClient", FakeRhino)
    result = asyncio.run(server.rhino_apply_operations(
        intent="create point",
        operations=[{"op": "create_point", "id": "point", "point": [0, 0, 0]}],
        idempotency_key="valid-test",
        document_revision="doc:10:99",
        checkpoint_path="C:/work/model.3dm",
    ))
    assert result["status"] == "completed"
    assert result["checkpoint"]["status"] == "saved"
    assert result["normalized_transaction"]["operations"][0]["op"] == "create_point"
    assert FakeDirect.executed == 1
