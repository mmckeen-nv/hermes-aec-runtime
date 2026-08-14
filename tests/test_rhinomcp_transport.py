import asyncio
import json
import socket
import threading

import pytest

from hermes_aec_runtime.rhinomcp_transport import (
    RhinoMCPAmbiguousWrite,
    RhinoMCPCommandError,
    RhinoMCPGateway,
    RhinoMCPTransport,
    RhinoMCPTransportError,
    _resolve_aliases,
)


def _serve_once(response, *, read_request=True):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0)); listener.listen(1)
    port = listener.getsockname()[1]
    observed = []

    def run():
        conn, _ = listener.accept()
        with conn:
            if read_request:
                length = int.from_bytes(conn.recv(4), "big")
                body = b""
                while len(body) < length:
                    body += conn.recv(length - len(body))
                observed.append(json.loads(body))
            if response is not None:
                body = json.dumps(response).encode()
                conn.sendall(len(body).to_bytes(4, "big") + body)
        listener.close()

    thread = threading.Thread(target=run); thread.start()
    return port, observed, thread


def test_wire_protocol_round_trip_and_unwrap():
    port, observed, thread = _serve_once({"status": "success", "result": {"object_count": 2}})
    result = asyncio.run(RhinoMCPTransport(port=port).call("get_document_summary", {}, read_attempts=1))
    thread.join()
    assert result == {"object_count": 2}
    assert observed == [{"type": "get_document_summary", "params": {}}]


def test_structured_error_is_not_success():
    port, _, thread = _serve_once({"status": "error", "message": "no document"})
    with pytest.raises(RhinoMCPCommandError, match="no document"):
        asyncio.run(RhinoMCPTransport(port=port).call("get_document_summary", {}, read_attempts=1))
    thread.join()


def test_lost_mutation_response_is_ambiguous_not_retried():
    port, observed, thread = _serve_once(None)
    with pytest.raises(RhinoMCPAmbiguousWrite):
        asyncio.run(RhinoMCPTransport(port=port).call("create_object", {"type": "POINT", "params": {}}))
    thread.join()
    assert len(observed) == 1


class FakeTransport:
    endpoint = "tcp://fake:1999"

    def __init__(self):
        self.objects = []
        self.calls = []
        self.ambiguous_create = False

    async def call(self, command, params=None, **_):
        params = params or {}; self.calls.append((command, params))
        if command == "describe_capabilities":
            return {"version": "0.3.2", "command_count": 4}
        if command == "get_document_summary":
            return {"meta_data": {"name": "Test", "units": "Millimeters"}, "object_count": len(self.objects)}
        if command == "get_objects":
            start, limit = params.get("offset", 0), params.get("limit", 500)
            return {"objects": self.objects[start:start + limit], "total_matching": len(self.objects)}
        if command == "create_object":
            oid = "11111111-1111-1111-1111-111111111111"
            self.objects.append({"id": oid, "name": "Point", "type": "POINT", "layer": "Default"})
            if self.ambiguous_create:
                raise RhinoMCPAmbiguousWrite("lost")
            return {"id": oid}
        if command == "delete_object":
            self.objects = [x for x in self.objects if x["id"] != params["id"]]
            return {"deleted": True}
        raise AssertionError(command)


def test_scene_index_paginates_and_has_content_revision():
    fake = FakeTransport()
    fake.objects = [{"id": f"00000000-0000-0000-0000-{i:012d}", "type": "POINT"} for i in range(5)]
    scene = asyncio.run(RhinoMCPGateway(fake).scene_index(page_size=2))
    assert len(scene["objects"]) == 5
    assert scene["document_revision"]
    assert [params["offset"] for cmd, params in fake.calls if cmd == "get_objects"] == [0, 2, 4]


def test_execute_resolves_aliases_verifies_and_replays():
    fake = FakeTransport(); gateway = RhinoMCPGateway(fake)
    operation = [{"op": "create_point", "id": "post", "point": [1, 2, 3]}]
    first = asyncio.run(gateway.execute_operations(intent="post", operations=operation, dry_run=False, idempotency_key="k1"))
    second = asyncio.run(gateway.execute_operations(intent="post", operations=operation, dry_run=False, idempotency_key="k1"))
    assert first["status"] == "completed" and first["verified"] is True
    assert first["outputs"]["post"] == ["11111111-1111-1111-1111-111111111111"]
    assert second["replayed"] is True
    assert len([x for x in fake.calls if x[0] == "create_object"]) == 1


def test_ambiguous_create_is_reconciled_without_replay():
    fake = FakeTransport(); fake.ambiguous_create = True
    receipt = asyncio.run(RhinoMCPGateway(fake).execute_operations(
        intent="post", operations=[{"op": "create_point", "id": "post", "point": [1, 2, 3]}],
        dry_run=False, idempotency_key="k2"))
    # A unique scene delta recovers the exact output without replaying the write.
    assert receipt["status"] == "reconciled"
    assert receipt["created_ids"] == ["11111111-1111-1111-1111-111111111111"]
    assert receipt["outputs"]["post"] == receipt["created_ids"]
    assert receipt["response_recovered"] is True


def test_unsupported_operations_fail_closed_or_use_narrow_legacy_fallback():
    operation = [{"op": "duplicate", "targets": ["11111111-1111-1111-1111-111111111111"]}]
    blocked = asyncio.run(RhinoMCPGateway(FakeTransport()).execute_operations(intent="copy", operations=operation))
    assert blocked["status"] == "blocked"

    calls = []
    async def legacy(**kwargs):
        calls.append(kwargs); return {"status": "validated", "transport": "legacy"}
    routed = asyncio.run(RhinoMCPGateway(FakeTransport(), legacy_executor=legacy).execute_operations(intent="copy", operations=operation))
    assert routed["transport"] == "legacy" and len(calls) == 1


def test_mixed_supported_and_unsupported_batch_never_falls_back():
    called = False
    async def legacy(**_):
        nonlocal called; called = True; return {}
    ops = [
        {"op": "create_point", "point": [0, 0, 0]},
        {"op": "duplicate", "targets": ["$op_1"]},
    ]
    result = asyncio.run(RhinoMCPGateway(FakeTransport(), legacy_executor=legacy).execute_operations(intent="mixed", operations=ops))
    assert result["status"] == "blocked" and called is False


def test_alias_resolution_expands_lists_and_rejects_ambiguous_scalar():
    assert _resolve_aliases({"object_ids": ["$a", "x"]}, {"a": ["1", "2"]}) == {"object_ids": ["1", "2", "x"]}
    with pytest.raises(RhinoMCPTransportError, match="exactly one"):
        _resolve_aliases({"id": "$a"}, {"a": ["1", "2"]})
