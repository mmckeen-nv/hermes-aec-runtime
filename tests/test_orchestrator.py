from __future__ import annotations

import asyncio

import pytest

from hermes_aec_runtime.flight_recorder import FlightRecorder
from hermes_aec_runtime.memory import MemoryDMLAdapter
from hermes_aec_runtime.orchestrator import WorkflowOrchestrator, build_plan


class FakeGateway:
    def __init__(self, *, receipt_status="completed", mutate=True):
        self.calls = []
        self.receipt_status = receipt_status
        self.mutate = mutate
        self.objects = [{"id": "existing", "name": "Pool", "kind": "mesh", "layer": "Site"}]

    async def query(self, query):
        self.calls.append(("query", query))
        return {"host": "rhino", "document": {"units": "meters"}, "objects": list(self.objects)}

    async def execute_typed(self, **kwargs):
        self.calls.append(("execute", kwargs))
        if kwargs["dry_run"]:
            return {"status": "validated", "transaction_id": "tx-1", "created_ids": [], "deleted_ids": []}
        created = []
        if self.receipt_status == "completed" and self.mutate:
            self.objects.append({"id": "fence", "name": "Pool Fence", "kind": "curve", "layer": "Site"})
            created = ["fence"]
        return {"status": self.receipt_status, "transaction_id": "tx-1", "created_ids": created, "deleted_ids": []}


class ThrowingGateway(FakeGateway):
    async def execute_typed(self, **kwargs):
        self.calls.append(("execute", kwargs))
        raise TimeoutError("response lost")


def test_plan_routes_and_compiles_before_touching_a_host():
    plan = build_plan("Add a fence around the pool", [{"op": "create_line", "start": [0, 0, 0], "end": [1, 0, 0]}])
    assert plan.route.intent.value == "modify"
    assert plan.query.terms == ("fence", "around", "pool")
    assert plan.normalized_transaction["operations"][0]["op"] == "create_line"
    assert len(plan.operation_signature) == 64


def test_plan_rejects_missing_or_surprising_operations():
    with pytest.raises(ValueError, match="requires"):
        build_plan("Delete the pool")
    with pytest.raises(ValueError, match="read-only"):
        build_plan("Inspect the pool", [{"op": "create_point", "point": [0, 0, 0]}])


def test_verified_workflow_records_and_promotes(tmp_path):
    gateway = FakeGateway()
    memory = MemoryDMLAdapter()
    recorder = FlightRecorder(tmp_path / "flight.jsonl")
    runner = WorkflowOrchestrator({"rhino": gateway}, recorder=recorder, memory=memory)
    result = asyncio.run(runner.run(
        request="Add a fence around the pool",
        operations=[{"op": "create_line", "start": [0, 0, 0], "end": [1, 0, 0]}],
        idempotency_key="project:fence:1", project_id="cliff-house",
        assertions={"object_count_delta": 1, "names_present": ["Pool Fence"]},
    ))
    assert result.status == "verified"
    assert [call[0] for call in gateway.calls] == ["query", "execute", "query"]
    assert result.memory.status == "promoted"
    assert result.trace_appended is True
    assert list(recorder.read())[0]["training_quality"]["accepted"] is True
    assert len(memory.list("cliff-house", "rhino", "promoted")) == 1


def test_dry_run_never_requeries_or_claims_verification(tmp_path):
    gateway = FakeGateway()
    runner = WorkflowOrchestrator({"rhino": gateway}, recorder=FlightRecorder(tmp_path / "flight.jsonl"))
    result = asyncio.run(runner.run(
        request="Add a fence", operations=[{"op": "create_point", "point": [0, 0, 0]}],
        idempotency_key="dry:1", dry_run=True,
    ))
    assert result.status == "validated"
    assert [call[0] for call in gateway.calls] == ["query", "execute"]
    assert result.verification["status"] == "not_run"
    assert result.memory.status == "rejected"
    assert list(FlightRecorder(tmp_path / "flight.jsonl").read())[0]["training_quality"]["accepted"] is False


def test_inspection_is_query_only_and_has_no_trace_side_effect(tmp_path):
    gateway = FakeGateway()
    recorder = FlightRecorder(tmp_path / "flight.jsonl")
    result = asyncio.run(WorkflowOrchestrator({"rhino": gateway}, recorder=recorder).run(request="Inspect pool"))
    assert result.status == "inspected"
    assert [call[0] for call in gateway.calls] == ["query"]
    assert not (tmp_path / "flight.jsonl").exists()


def test_failed_receipt_is_recorded_but_not_retried_or_promoted(tmp_path):
    gateway = FakeGateway(receipt_status="failed")
    memory = MemoryDMLAdapter()
    result = asyncio.run(WorkflowOrchestrator(
        {"rhino": gateway}, recorder=FlightRecorder(tmp_path / "flight.jsonl"), memory=memory,
    ).run(
        request="Delete the pool", operations=[{"op": "delete", "targets": ["00000000-0000-0000-0000-000000000001"]}],
        idempotency_key="delete:1", project_id="cliff-house",
    ))
    assert result.status == "failed"
    assert [call[0] for call in gateway.calls] == ["query", "execute"]
    assert result.memory.status == "rejected"


def test_lost_mutation_response_becomes_unknown_receipt_without_retry(tmp_path):
    gateway = ThrowingGateway()
    recorder = FlightRecorder(tmp_path / "flight.jsonl")
    result = asyncio.run(WorkflowOrchestrator({"rhino": gateway}, recorder=recorder).run(
        request="Add a fence", operations=[{"op": "create_point", "point": [0, 0, 0]}],
        idempotency_key="lost:1",
    ))
    assert result.status == "unknown"
    assert [call[0] for call in gateway.calls] == ["query", "execute"]
    assert result.receipt["recovery"].startswith("Re-index")
    assert result.memory.status == "rejected"
    assert len(list(recorder.read())) == 1
