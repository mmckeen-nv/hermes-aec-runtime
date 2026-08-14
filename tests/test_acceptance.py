import asyncio
import json
from contextlib import asynccontextmanager
from hashlib import sha256
from uuid import uuid4

from hermes_aec_runtime.operations import compile_transaction
from hermes_aec_runtime.rhino import RhinoClient
from hermes_aec_runtime.scene_index import SCENE_SCHEMA_VERSION, SceneIndex
from hermes_aec_runtime.supervisor import CheckpointStore, HostState, PortStatus, ProcessStatus, RecoveryAction, RhinoHostSupervisor
from hermes_aec_runtime.verification import verify_transaction


class RetryReadClient(RhinoClient):
    def __init__(self):
        super().__init__(url="http://unused/", read_attempts=3)
        object.__setattr__(self, "attempts", 0)

    @asynccontextmanager
    async def session(self):
        self.attempts += 1
        if self.attempts < 3:
            raise ConnectionError("transient bridge failure")
        yield object()


def test_read_retry_reconnects_and_succeeds():
    client = RetryReadClient()
    result = asyncio.run(client._read_sequence(lambda _session: asyncio.sleep(0, result="ready")))
    assert result == "ready"
    assert client.attempts == 3


class LostResponseClient(RhinoClient):
    def __init__(self, fingerprint):
        super().__init__(url="http://unused/")
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "mutations", 0)
        object.__setattr__(self, "recoveries", 0)

    @asynccontextmanager
    async def session(self):
        yield object()

    async def _call(self, _session, name, _arguments):
        if name == "run_python": self.mutations += 1
        raise ConnectionError("response lost after commit")

    async def _recover_receipt(self, transaction_id):
        self.recoveries += 1
        if self.recoveries == 1: return None
        return {"schema_version": "1.0", "transaction_id": transaction_id,
                "fingerprint": self.fingerprint, "status": "completed",
                "before_count": 1, "after_count": 2, "created_ids": ["new"],
                "deleted_ids": [], "rolled_back": False}


def test_lost_mutation_response_and_duplicate_suppression():
    intent, script, expected = "create probe", "print(__rhino_doc__.Name)", "one probe"
    fingerprint = sha256(f"{intent}\0{script}\0{expected}".encode()).hexdigest()
    client = LostResponseClient(fingerprint)
    key = "acceptance-lost-" + uuid4().hex
    first = asyncio.run(client.execute_python(intent=intent, script=script, expected_change=expected, dry_run=False, idempotency_key=key))
    second = asyncio.run(client.execute_python(intent=intent, script=script, expected_change=expected, dry_run=False, idempotency_key=key))
    assert first["status"] == "completed" and first["response_recovered"] is True
    assert second["replayed"] is True
    assert client.mutations == 1


class RollbackClient(RhinoClient):
    def __init__(self):
        super().__init__(url="http://unused/")
        object.__setattr__(self, "commands", [])

    async def _recover_receipt(self, _transaction_id): return None

    @asynccontextmanager
    async def session(self): yield object()

    async def _call(self, _session, name, arguments):
        self.commands.append(name)
        if name == "run_command": return {"stdout": "Undoing Hermes AEC"}
        if "sum(1 for _" in arguments.get("script", ""): return {"stdout": '{"count": 4}'}
        fingerprint = sha256("break\0raise Exception('boom')\0no residue".encode()).hexdigest()
        return {"stdout": "HERMES_AEC_RECEIPT=" + json.dumps({
            "status": "failed", "transaction_id": "tx", "fingerprint": fingerprint,
            "before_count": 4, "after_count": 5, "created_ids": ["partial"],
            "deleted_ids": [], "attempted_created_ids": ["partial"], "rolled_back": False,
            "error": "boom"})}


def test_failed_mutation_rolls_back_to_zero_residue():
    client = RollbackClient()
    receipt = asyncio.run(client.execute_python(intent="break", script="raise Exception('boom')",
        expected_change="no residue", dry_run=False, idempotency_key="acceptance-rollback-" + uuid4().hex))
    assert receipt["status"] == "failed" and receipt["rolled_back"] is True
    assert receipt["after_count"] == receipt["before_count"] and receipt["created_ids"] == []
    assert "run_command" in client.commands


class DownProbe:
    def process_status(self): return ProcessStatus(False, exit_code=1)
    def port_status(self, _port): return PortStatus(False)
    def mcp_ready(self): return False


def test_host_down_produces_conservative_recovery_plan(tmp_path):
    plan = RhinoHostSupervisor(DownProbe(), CheckpointStore(tmp_path / "checkpoint.json")).recovery_plan()
    assert plan.state is HostState.CRASHED
    assert plan.actions == (RecoveryAction.RESTART_RHINO, RecoveryAction.RESUME)
    assert plan.automatic is True


def _scene(objects):
    return {"schema_version": SCENE_SCHEMA_VERSION, "document_revision": "mock:1",
            "document": {"units": "Meters"}, "units": "Meters", "tolerance": 0.001,
            "layers": ["AEC::Building", "AEC::Site"], "relationships": [], "objects": objects}


def test_scene_query_operation_verification_flow_has_zero_residue():
    house = {"id": "house", "name": "Cliff House", "kind": "Brep", "layer": "AEC::Building",
             "visible": True, "locked": False, "bounds": {"min": [0, 0, 0], "max": [31, 34, 15.4]}}
    before = _scene([house])
    assert [obj["id"] for obj in SceneIndex(before).query(name="Cliff*", kind="Brep")] == ["house"]
    compiled = compile_transaction([
        {"op": "create_box", "id": "probe", "min": [40, 40, 0], "max": [41, 41, 1]},
        {"op": "set_attributes", "targets": ["$probe"], "name": "AEC Acceptance Probe"},
        {"op": "delete", "targets": ["$probe"]}])
    assert "create_box" in compiled.expected_change and "delete" in compiled.expected_change
    after = _scene([house])
    receipt = {"status": "completed", "transaction_id": compiled.fingerprint, "created_ids": [], "deleted_ids": []}
    result = verify_transaction(receipt, before, after, {"object_count_delta": 0,
        "names_absent": ["AEC Acceptance Probe"], "units": "meters"})
    assert result.status == "verified"
    assert len(before["objects"]) == len(after["objects"])
