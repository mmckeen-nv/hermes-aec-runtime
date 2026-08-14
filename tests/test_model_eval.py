from __future__ import annotations

import json
from pathlib import Path

from hermes_aec_runtime.model_eval import (
    ReadinessThresholds, audit_dataset, evaluate_suite, evaluate_task,
)


def task(host="rhino"):
    return {
        "id": "t1", "prompt": "Move the wall", "host": host,
        "expected": {"route": "modify", "allowed_tools": ["transform_in_place"]},
        "budget": {"max_tool_calls": 4, "max_elapsed_ms": 1000, "max_input_tokens": 1000,
                   "max_output_tokens": 500, "max_operations": 2, "max_script_bytes": 1},
    }


def candidate(host="rhino"):
    return {
        "route": {"kind": "modify", "host": host}, "tools": ["transform_in_place"],
        "transaction": {"schema_version": "1.0.0", "kind": "operation_transaction",
                        "id": "tx-1", "created_at": 0, "host": host, "document_revision": 5,
                        "idempotency_key": "stable-1", "operations": [{"op": "transform_in_place"}]},
        "verification": {"required": True},
        "usage": {"tool_calls": 3, "elapsed_ms": 100, "input_tokens": 500,
                  "output_tokens": 100, "operations": 1, "script_bytes": 0},
    }


def test_valid_candidate_passes_every_metric():
    result = evaluate_task(task(), candidate())
    assert result.passed
    assert result.score == 1.0
    assert all(value == 1.0 for value in result.metrics.values())


def test_wrong_host_script_and_budget_fail_closed():
    value = candidate("blender")
    value["transaction"]["operations"] = [{"op": "script"}]
    value["tools"] = ["script"]
    value["usage"]["elapsed_ms"] = 1001
    result = evaluate_task(task(), value)
    assert not result.passed
    assert {"host_selection", "transaction_validity", "safety_idempotency", "tool_choice", "budget_compliance"} <= set(result.failures)


def test_missing_idempotency_and_verification_are_critical_failures():
    value = candidate()
    del value["transaction"]["idempotency_key"]
    value["verification"] = {"required": False}
    result = evaluate_task(task(), value)
    assert not result.passed
    assert "safety_idempotency" in result.failures
    assert "verification_discipline" in result.failures


def test_dataset_audit_detects_duplicates_contamination_and_secrets():
    rows = [
        {"prompt": "Move the wall", "host": "rhino", "token": "sk-abcdefghijk"},
        {"prompt": "Move the wall", "host": "rhino", "token": "sk-abcdefghijk"},
    ]
    audit = audit_dataset(rows, [task()], ReadinessThresholds(minimum_training_examples=1))
    assert not audit.sufficient
    assert audit.duplicate_fraction == 0.5
    assert audit.contamination_fraction == 1.0
    assert audit.secret_findings == 2


def test_suite_separates_model_quality_from_dataset_readiness():
    tasks = [{**task(), "id": f"t{i}", "prompt": f"Move wall {i}"} for i in range(2)]
    candidates = {item["id"]: candidate() for item in tasks}
    report = evaluate_suite(tasks, candidates, thresholds=ReadinessThresholds(minimum_tasks=2, minimum_training_examples=1))
    assert report.overall_score == 1.0
    assert report.decision == "NO-GO"
    assert "training examples 0 < 1" in report.blockers


def test_clean_sufficient_suite_is_go():
    tasks = [{**task(), "id": f"t{i}", "prompt": f"Eval prompt {i}"} for i in range(2)]
    candidates = {item["id"]: candidate() for item in tasks}
    training = [{"prompt": f"Training prompt {i}", "host": "rhino", "transaction": {"id": i}} for i in range(3)]
    thresholds = ReadinessThresholds(minimum_tasks=2, minimum_training_examples=3)
    report = evaluate_suite(tasks, candidates, training_examples=training, thresholds=thresholds)
    assert report.fine_tune_ready
    assert report.decision == "GO"


def test_baseline_fixture_has_required_host_coverage():
    path = Path(__file__).parents[1] / "evals" / "baseline_tasks.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert len(rows) >= 20
    assert {row["host"] for row in rows} == {"rhino", "blender"}
