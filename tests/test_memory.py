import json

from hermes_aec_runtime.memory import FilesystemDMLAdapter, MemoryDMLAdapter, PromotionPolicy, create_outcome


def _outcome(**overrides):
    receipt = {"transaction_id": "tx-1", "status": "completed", "actions_attempted": 1, "actions_completed": 1, "created_ids": ["id-1"], "prompt": "do secret work", "api_key": "sk-supersecret"}
    verification = {"status": "verified", "passed": ["geometry exists"], "failed": []}
    args = dict(project_id="cliff-house", host="Rhino", receipt=receipt, verification=verification, operation_signature="create_box:v1", trace=[{"tool": "typed_execute", "duration_ms": 12, "success": True, "authorization": "Bearer secret-value", "messages": ["raw"]}])
    args.update(overrides)
    return create_outcome(**args)


def test_verified_outcome_is_promoted_and_sanitized():
    outcome = _outcome()
    encoded = json.dumps(outcome.to_dict())
    assert outcome.status == "promoted"
    assert outcome.quality_score == 1.0
    assert "supersecret" not in encoded and "secret-value" not in encoded and "raw" not in encoded
    assert "prompt" not in outcome.receipt and "authorization" not in outcome.trace_summary[0]


def test_failed_or_unverified_outcomes_are_rejected():
    assert _outcome(receipt={"transaction_id": "x", "status": "failed", "actions_attempted": 1, "actions_completed": 0}, verification={"status": "failed", "failed": ["no delta"]}).status == "rejected"
    assert _outcome(verification={"status": "failed", "failed": ["wrong bounds"]}).status == "rejected"


def test_policy_can_quarantine_a_verified_slow_outcome():
    outcome = _outcome(trace=[{"duration_ms": 100}], policy=PromotionPolicy(promote_score=.95, quarantine_score=.60, maximum_duration_ms=10))
    assert outcome.status == "quarantined"
    assert outcome.quality_score == .9


def test_deduplication_is_deterministic_and_scoped():
    adapter = MemoryDMLAdapter()
    first = _outcome()
    duplicate = _outcome(trace=[{"duration_ms": 999}])
    other_host = _outcome(host="Blender")
    assert first.outcome_id == duplicate.outcome_id
    assert adapter.put(first) is True
    assert adapter.put(duplicate) is False
    assert adapter.put(other_host) is True
    assert len(adapter.list("cliff-house", "rhino")) == 1
    assert len(adapter.list("cliff-house", "blender")) == 1


def test_filesystem_adapter_writes_only_sanitized_records(tmp_path):
    adapter = FilesystemDMLAdapter(tmp_path)
    outcome = _outcome()
    assert adapter.put(outcome) is True
    assert adapter.put(outcome) is False
    content = next(tmp_path.rglob("*.json")).read_text(encoding="utf-8")
    assert "raw" not in content and "sk-" not in content
    assert json.loads(content)["status"] == "promoted"
    reopened = FilesystemDMLAdapter(tmp_path)
    assert reopened.get("cliff-house", "RHINO", outcome.outcome_id) == outcome
    assert reopened.list("cliff-house", "rhino", status="promoted") == [outcome]
