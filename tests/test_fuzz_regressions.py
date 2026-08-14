"""Deterministic property-style regression tests for hostile boundary inputs."""
from __future__ import annotations

import asyncio
import math
import random

import pytest

from hermes_aec_runtime.blender_operations import BlenderOperationError, normalize_blender_operations
from hermes_aec_runtime.contract import ContractError, canonical_json, validate_envelope, validate_transaction
from hermes_aec_runtime.freecad_operations import FreeCADOperationError, normalize_freecad_operations
from hermes_aec_runtime.flight_recorder import make_trace
from hermes_aec_runtime.memory import create_outcome, redact
from hermes_aec_runtime.operations import OperationValidationError, normalize_operations
from hermes_aec_runtime.orchestrator import WorkflowOrchestrator, build_plan
from hermes_aec_runtime.router import route_request


@pytest.mark.parametrize("bad", [None, "x", 1, True, math.nan, math.inf, {}, [[]]])
def test_compilers_reject_wrong_top_level_without_host_side_effects(bad):
    for compiler, error in (
        (normalize_operations, OperationValidationError),
        (normalize_blender_operations, BlenderOperationError),
        (normalize_freecad_operations, FreeCADOperationError),
    ):
        with pytest.raises(error):
            compiler(bad)  # type: ignore[arg-type]


def test_seeded_malformed_numeric_vectors_are_always_rejected():
    rng = random.Random(20260814)
    bad_scalars = [None, True, False, "1", math.nan, math.inf, -math.inf, {}, []]
    for _ in range(100):
        vector = [rng.choice(bad_scalars) for _ in range(3)]
        with pytest.raises(OperationValidationError):
            normalize_operations([{"op": "create_point", "point": vector}])


def test_boolean_coercion_and_unknown_fields_are_rejected():
    with pytest.raises(OperationValidationError):
        normalize_operations([{"op": "create_polyline", "points": [[0, 0, 0], [1, 0, 0]], "closed": "false"}])
    with pytest.raises(BlenderOperationError):
        normalize_blender_operations([{"op": "ensure_collection", "name": "x", "typo": 1}])
    with pytest.raises(FreeCADOperationError):
        normalize_freecad_operations([{"op": "transform", "target": "x", "rotation_axis": [0, 0, 0]}])


def test_extreme_batches_are_bounded():
    rhino = [{"op": "create_point", "point": [i, 0, 0]} for i in range(257)]
    blender = [{"op": "ensure_collection", "name": str(i)} for i in range(257)]
    freecad = [{"op": "delete", "target": str(i)} for i in range(257)]
    with pytest.raises(OperationValidationError): normalize_operations(rhino)
    with pytest.raises(BlenderOperationError): normalize_blender_operations(blender)
    with pytest.raises(FreeCADOperationError): normalize_freecad_operations(freecad)


def test_contract_rejects_non_json_and_bool_integer_fields():
    with pytest.raises(ContractError): canonical_json({"x": math.nan})
    cycle: list[object] = []; cycle.append(cycle)
    with pytest.raises(ContractError): canonical_json(cycle)
    with pytest.raises(ContractError): validate_envelope([], "x")  # type: ignore[arg-type]
    envelope = {"schema_version": "1.0.0", "kind": "operation_transaction", "id": "x", "created_at": 0,
                "document_revision": True, "idempotency_key": "x", "operations": [{"op": "create_point"}]}
    with pytest.raises(ContractError): validate_transaction(envelope)


def test_recursive_and_nonfinite_memory_values_are_sanitized():
    cycle: dict[str, object] = {}; cycle["nested"] = cycle
    assert redact(cycle) == {"nested": "[CYCLE]"}
    assert redact({"duration": math.inf}) == {"duration": "[NON_FINITE]"}
    outcome = create_outcome(
        project_id="p", host="rhino", operation_signature="s",
        receipt={"status": "completed", "transaction_id": "x", "actions_attempted": {}},
        verification={"status": "verified", "failed": []},
        trace=[{"duration_ms": "not-a-number"}],
    )
    assert outcome.quality_score >= 0
    trace = make_trace(request="inspect", route={"intent": "inspect"}, scene_subset=cycle,
                       transaction={}, timing={"duration_ms": math.nan}, tool_outcomes=[],
                       receipt={"status": "failed"}, verification={"status": "failed"}, created_at=0)
    assert trace["scene_subset"]["content_hash"].startswith("sha256:")
    assert canonical_json(trace)


def test_router_and_plan_bound_external_inputs():
    for host in ("", "maya", None, 3):
        with pytest.raises(ValueError): route_request("inspect", active_host=host)  # type: ignore[arg-type]


def test_invalid_mutation_never_queries_or_executes_host():
    class Host:
        calls = 0
        async def query(self, query): self.calls += 1; return {}
        async def execute_typed(self, **kwargs): self.calls += 1; return {}
    host = Host()
    runner = WorkflowOrchestrator({"rhino": host})
    with pytest.raises(OperationValidationError):
        asyncio.run(runner.run(request="add point", operations=[{"op": "create_point", "point": [math.nan, 0, 0]}], idempotency_key="x"))
    assert host.calls == 0
