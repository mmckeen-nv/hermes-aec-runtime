"""Host-neutral lifecycle primitives for deterministic AEC adapters."""
from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

HOST_SCENE_SCHEMA_VERSION = "aec-scene-index/1.0"
HOST_RECEIPT_SCHEMA_VERSION = "aec-execution-receipt/1.0"


def content_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def finalize_scene(*, host: str, document_id: str, units: str, objects: list[dict[str, Any]], document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate stable identity and emit the common scene envelope."""
    ids = [str(item.get("id") or "").strip() for item in objects]
    if any(not item for item in ids):
        raise ValueError(f"{host} scene contains an object without a stable ID")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{host} scene contains duplicate stable IDs")
    normalized = sorted(objects, key=lambda item: str(item["id"]))
    revision = content_hash({"document_id": document_id, "units": units, "objects": normalized})
    return {
        "schema_version": HOST_SCENE_SCHEMA_VERSION, "scene_contract_version": HOST_SCENE_SCHEMA_VERSION, "host": host,
        "document_id": document_id, "document_revision": revision, "units": units,
        "document": document or {}, "objects": normalized, "count": len(normalized),
    }


def scene_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[str]]:
    prior = {str(item["id"]): item for item in before.get("objects", [])}
    current = {str(item["id"]): item for item in after.get("objects", [])}
    shared = prior.keys() & current.keys()
    return {
        "created_ids": sorted(current.keys() - prior.keys()),
        "modified_ids": sorted(key for key in shared if prior[key].get("content_hash") != current[key].get("content_hash")),
        "deleted_ids": sorted(prior.keys() - current.keys()),
    }


def completed_receipt(*, host: str, transaction_id: str, intent: str, fingerprint: str, before: dict[str, Any], after: dict[str, Any], result: Any) -> dict[str, Any]:
    return {
        "schema_version": HOST_RECEIPT_SCHEMA_VERSION, "host": host, "status": "completed",
        "transaction_id": transaction_id, "intent": intent, "fingerprint": fingerprint,
        "before_revision": before["document_revision"], "after_revision": after["document_revision"],
        **scene_delta(before, after), "result": result,
    }


def blocked_stale(*, host: str, transaction_id: str, expected: str, current: str, fingerprint: str = "") -> dict[str, Any]:
    return {"schema_version": HOST_RECEIPT_SCHEMA_VERSION, "host": host, "status": "blocked", "transaction_id": transaction_id,
            "fingerprint": fingerprint, "created_ids": [], "modified_ids": [], "deleted_ids": [],
            "error": "document revision changed after the focused query", "expected_document_revision": expected, "current_document_revision": current}


def lifecycle_receipt(*, host: str, transaction_id: str, status: str, fingerprint: str, **values: Any) -> dict[str, Any]:
    """Build a receipt envelope for non-completed lifecycle states."""
    return {"schema_version": HOST_RECEIPT_SCHEMA_VERSION, "host": host, "status": status,
            "transaction_id": transaction_id, "fingerprint": fingerprint,
            "created_ids": [], "modified_ids": [], "deleted_ids": [], **values}


def recovery_plan(receipt: dict[str, Any], host_label: str) -> dict[str, Any]:
    status = receipt.get("status")
    if status == "unknown":
        return {"action": "reconcile", "retry_policy": "same_key_only", "steps": [f"Re-index the {host_label} document", "Compare the intended object delta", "Retry only with the same idempotency key"]}
    if status == "failed":
        return {"action": "verify_rollback", "retry_policy": "new_key_after_correction", "steps": ["Confirm rollback or undo", "Re-index and verify zero residue"]}
    if status == "blocked":
        return {"action": "replan", "retry_policy": "new_revision_required", "steps": [f"Re-index the {host_label} document", "Rebuild the transaction against the current revision"]}
    return {"action": "verify", "retry_policy": "none", "steps": ["Re-index changed objects", "Verify created, modified, and deleted IDs against the receipt"]}
