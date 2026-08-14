import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256

from hermes_aec_runtime.rhino import RhinoClient


class RecoveringClient(RhinoClient):
    def __init__(self):
        super().__init__(url="http://unused/")
        object.__setattr__(self, "recoveries", 0)

    @asynccontextmanager
    async def session(self):
        yield object()

    async def _call(self, session, name, arguments):
        raise ConnectionError("response lost after execution")

    async def _recover_receipt(self, transaction_id):
        self.recoveries += 1
        if self.recoveries == 1:
            return None
        return {
            "schema_version": "1.0", "transaction_id": transaction_id,
            "fingerprint": sha256(
                "create one object\0print(__rhino_doc__.Name)\0one object".encode()
            ).hexdigest(),
            "status": "completed", "before_count": 10, "after_count": 11,
            "created_ids": ["created-on-rhino"], "deleted_ids": [],
            "rolled_back": False,
        }


def test_lost_mutation_response_recovers_persisted_receipt():
    client = RecoveringClient()
    receipt = asyncio.run(client.execute_python(
        intent="create one object",
        script="print(__rhino_doc__.Name)",
        expected_change="one object",
        dry_run=False,
        idempotency_key="lost-response-test",
    ))
    assert receipt["status"] == "completed"
    assert receipt["response_recovered"] is True
    assert receipt["created_ids"] == ["created-on-rhino"]


def test_same_idempotency_key_replays_without_second_mutation():
    client = RecoveringClient()
    first = asyncio.run(client.execute_python(
        intent="create one object",
        script="print(__rhino_doc__.Name)",
        expected_change="one object",
        dry_run=False,
        idempotency_key="replay-test",
    ))
    second = asyncio.run(client.execute_python(
        intent="create one object",
        script="print(__rhino_doc__.Name)",
        expected_change="one object",
        dry_run=False,
        idempotency_key="replay-test",
    ))
    assert first["transaction_id"] == second["transaction_id"]
    assert second["replayed"] is True


def test_changed_payload_cannot_reuse_idempotency_key():
    client = RecoveringClient()
    asyncio.run(client.execute_python(
        intent="create one object",
        script="print(__rhino_doc__.Name)",
        expected_change="one object",
        dry_run=False,
        idempotency_key="payload-conflict-test",
    ))
    conflict = asyncio.run(client.execute_python(
        intent="create one object",
        script="import System\nprint(__rhino_doc__.Name)",
        expected_change="one object",
        dry_run=False,
        idempotency_key="payload-conflict-test",
    ))
    assert conflict["status"] == "blocked"
    assert "different payload" in conflict["error"]
