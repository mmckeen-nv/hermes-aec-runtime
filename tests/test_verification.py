from hermes_aec_runtime.verification import verify_transaction


def scene(*objects, units="Meters"):
    return {"document": {"units": units}, "objects": list(objects)}


def test_verifies_receipt_and_independent_delta():
    before = scene({"id": "old", "name": "House"})
    after = scene({"id": "old", "name": "House"}, {"id": "new", "name": "Rail"})
    receipt = {"status": "completed", "transaction_id": "tx", "created_ids": ["new"], "deleted_ids": []}
    result = verify_transaction(receipt, before, after, {
        "object_count_delta": 1, "names_present": ["Rail"], "units": "meters",
    })
    assert result.status == "verified"
    assert not result.failed


def test_fails_when_receipt_claim_does_not_match_scene():
    before = scene({"id": "old", "name": "House"})
    after = scene({"id": "old", "name": "House"}, {"id": "copy", "name": "Unexpected Copy"})
    receipt = {"status": "completed", "transaction_id": "tx", "created_ids": [], "deleted_ids": []}
    result = verify_transaction(receipt, before, after, {"object_count_delta": 0})
    assert result.status == "failed"
    assert any("created ID mismatch" in item for item in result.failed)

