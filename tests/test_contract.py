import json
from pathlib import Path

import pytest

from hermes_aec_runtime.contract import (
    CONTRACT_VERSION, BudgetUsage, ContractError, RuntimeBudget, SafetyPolicy,
    TransactionState, assert_compatible, canonical_json, content_hash,
    make_envelope, transition, validate_envelope, validate_receipt,
    validate_transaction,
)


def test_budget_defaults_and_exact_boundary():
    budget = RuntimeBudget()
    usage = BudgetUsage()
    usage.charge(budget, tool_calls=8, elapsed_ms=120_000, input_tokens=64_000,
                 output_tokens=8_192, operations=64, script_bytes=65_536)
    assert usage.operations == 64


@pytest.mark.parametrize("field", RuntimeBudget.__dataclass_fields__)
def test_each_budget_rejects_nonpositive(field):
    values = {field: 0}
    with pytest.raises(ContractError, match=field):
        RuntimeBudget(**values)


@pytest.mark.parametrize("counter,limit", [
    ("tool_calls", 8), ("elapsed_ms", 120_000), ("input_tokens", 64_000),
    ("output_tokens", 8_192), ("operations", 64), ("script_bytes", 65_536),
])
def test_each_budget_overflow_fails(counter, limit):
    with pytest.raises(ContractError, match=counter):
        BudgetUsage().charge(RuntimeBudget(), **{counter: limit + 1})


def test_invalid_charges_fail():
    with pytest.raises(ContractError, match="non-negative"):
        BudgetUsage().charge(RuntimeBudget(), operations=-1)
    with pytest.raises(ContractError, match="unknown"):
        BudgetUsage().charge(RuntimeBudget(), bananas=1)


@pytest.mark.parametrize("source,target", [
    ("planned", "validated"), ("planned", "failed"),
    ("validated", "executing"), ("validated", "failed"),
    ("executing", "completed"), ("executing", "failed"), ("executing", "unknown"),
    ("unknown", "completed"), ("unknown", "failed"), ("unknown", "rolled_back"),
    ("failed", "rolled_back"),
])
def test_allowed_transitions(source, target):
    assert transition(source, target) is TransactionState(target)


def test_all_other_transitions_fail():
    allowed = {(a.value, b.value) for a in TransactionState for b in TransactionState
               if a != b and _transition_ok(a, b)}
    for source in TransactionState:
        for target in TransactionState:
            if (source.value, target.value) not in allowed:
                with pytest.raises(ContractError):
                    transition(source, target)


def _transition_ok(source, target):
    try:
        transition(source, target)
        return True
    except ContractError:
        return False


def transaction(**updates):
    value = make_envelope("operation_transaction", "tx-1", document_revision=2,
                          idempotency_key="stable-key", operations=[{"op": "move"}])
    value.update(updates)
    return value


def test_transaction_invariants_and_script_policy():
    validate_transaction(transaction())
    for key in ("document_revision", "idempotency_key"):
        value = transaction(); value.pop(key)
        with pytest.raises(ContractError, match=key): validate_transaction(value)
    with pytest.raises(ContractError, match="non-empty"):
        validate_transaction(transaction(operations=[]))
    with pytest.raises(ContractError, match="op is required"):
        validate_transaction(transaction(operations=[{}]))
    with pytest.raises(ContractError, match="forbidden"):
        validate_transaction(transaction(operations=[{"op": "script"}]))
    validate_transaction(transaction(operations=[{"op": "script"}]),
                         SafetyPolicy(permit_arbitrary_script=True))


def test_envelope_and_receipt_validation():
    envelope = make_envelope("scene_index", "scene-1")
    validate_envelope(envelope, "scene_index")
    with pytest.raises(ContractError, match="unsupported"):
        validate_envelope({**envelope, "schema_version": "2.0.0"}, "scene_index")
    receipt = make_envelope("execution_receipt", "r-1", transaction_id="tx-1", state="completed")
    validate_receipt(receipt)
    with pytest.raises(ContractError, match="state"):
        validate_receipt({**receipt, "state": "maybe"})


def test_hash_is_canonical_and_stable():
    assert canonical_json({"é": 1, "a": 2}) == '{"a":2,"é":1}'
    assert content_hash({"b": 1, "a": 2}) == content_hash({"a": 2, "b": 1})
    assert content_hash({"a": 2}).startswith("sha256:")
    assert len(content_hash({"a": 2})) == 71


@pytest.mark.parametrize("producer,consumer", [("1.0.0", "1.0.0"), ("1.0.9", "1.0.0"), ("1.1.0", "1.2.0")])
def test_compatible_versions(producer, consumer):
    assert_compatible(producer, consumer)


@pytest.mark.parametrize("producer,consumer", [("2.0.0", "1.0.0"), ("1.1.0", "1.0.0"), ("wat", "1.0.0")])
def test_incompatible_versions(producer, consumer):
    with pytest.raises(ContractError): assert_compatible(producer, consumer)


def test_schema_catalog_and_eval_fixtures_are_complete():
    root = Path(__file__).parents[1] / "schemas"
    expected = {"aec-common-v1.json", "scene-index-v1.json", "request-route-v1.json",
                "operation-transaction-v1.json", "execution-receipt-v1.json",
                "verification-result-v1.json", "runtime-budget-v1.json",
                "safety-policy-v1.json", "trace-envelope-v1.json",
                "evaluation-task-v1.json", "evaluation-result-v1.json"}
    # Other independently versioned subsystems may add schemas to the catalog.
    assert expected <= {p.name for p in root.glob("*.json")}
    for path in root.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(document, dict)
    for fixture in (root / "fixtures").glob("*.json"):
        document = json.loads(fixture.read_text(encoding="utf-8"))
        validate_envelope(document, "evaluation_task")
        assert document["schema_version"] == CONTRACT_VERSION
