import pytest

from hermes_aec_runtime.host_contract import (
    HOST_RECEIPT_SCHEMA_VERSION, HOST_SCENE_SCHEMA_VERSION, completed_receipt,
    finalize_scene, recovery_plan, scene_delta,
)
from hermes_aec_runtime.verification import verify_transaction


def _object(identity, value):
    return {"id": identity, "name": identity, "kind": "solid", "layer": "AEC", "content_hash": f"hash-{value}"}


@pytest.mark.parametrize("host", ["rhino", "blender", "freecad"])
def test_every_host_satisfies_shared_scene_receipt_verification_and_recovery_lifecycle(host):
    before = finalize_scene(host=host, document_id="doc-1", units="meters", objects=[_object("wall", 1), _object("old", 1)])
    after = finalize_scene(host=host, document_id="doc-1", units="meters", objects=[_object("wall", 2), _object("new", 1)])
    assert before["schema_version"] == HOST_SCENE_SCHEMA_VERSION
    assert before["scene_contract_version"] == HOST_SCENE_SCHEMA_VERSION
    assert before["document_revision"] != after["document_revision"]
    assert scene_delta(before, after) == {"created_ids": ["new"], "modified_ids": ["wall"], "deleted_ids": ["old"]}

    receipt = completed_receipt(host=host, transaction_id="tx-1", intent="edit", fingerprint="fp", before=before, after=after, result={"ok": True})
    assert receipt["schema_version"] == HOST_RECEIPT_SCHEMA_VERSION
    assert receipt["created_ids"] == ["new"] and receipt["modified_ids"] == ["wall"] and receipt["deleted_ids"] == ["old"]
    assert receipt["before_revision"] == before["document_revision"] and receipt["after_revision"] == after["document_revision"]
    assert verify_transaction(receipt, before, after).status == "verified"
    assert recovery_plan(receipt, host)["action"] == "verify"
    assert recovery_plan({"status": "unknown"}, host)["retry_policy"] == "same_key_only"
    assert recovery_plan({"status": "blocked"}, host)["retry_policy"] == "new_revision_required"


@pytest.mark.parametrize("objects", [[{"id": "", "content_hash": "x"}], [{"id": "same"}, {"id": "same"}]])
def test_common_scene_contract_fails_closed_on_unstable_identity(objects):
    with pytest.raises(ValueError):
        finalize_scene(host="blender", document_id="doc", units="meters", objects=objects)
