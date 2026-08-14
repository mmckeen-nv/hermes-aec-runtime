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


def test_fails_closed_when_scene_identity_is_missing_or_duplicated():
    receipt = {"status": "completed", "transaction_id": "tx", "created_ids": [], "deleted_ids": []}
    missing = verify_transaction(receipt, scene({"name": "Wall"}), scene({"name": "Wall"}))
    duplicate = verify_transaction(receipt, scene({"id": "same"}, {"id": "same"}), scene({"id": "same"}, {"id": "same"}))
    assert missing.status == "failed"
    assert any("without stable IDs" in item for item in missing.failed)
    assert duplicate.status == "failed"
    assert any("duplicate stable ID" in item for item in duplicate.failed)


def test_independently_proves_in_place_modification_by_content_hash():
    before = scene({"id":"wall", "name":"Wall", "content_hash":"before"})
    after = scene({"id":"wall", "name":"Wall", "content_hash":"after"})
    receipt = {"status":"completed", "created_ids":[], "deleted_ids":[], "operation_result":{"modified":["wall"]}}
    result = verify_transaction(receipt, before, after)
    assert result.status == "verified"
    assert any("content changed" in item for item in result.passed)


def test_fails_in_place_modification_without_independent_hash_change():
    before = scene({"id":"wall", "content_hash":"same"})
    after = scene({"id":"wall", "content_hash":"same"})
    receipt = {"status":"completed", "created_ids":[], "deleted_ids":[], "modified_ids":["wall"]}
    result = verify_transaction(receipt, before, after)
    assert result.status == "failed"
    assert any("did not change" in item for item in result.failed)
