from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Any


@dataclass(frozen=True)
class VerificationResult:
    status: str
    passed: tuple[str, ...]
    failed: tuple[str, ...]
    transaction_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": self.status,
            "transaction_id": self.transaction_id,
            "passed": list(self.passed),
            "failed": list(self.failed),
        }


def _objects(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return list(scene.get("objects") or [])


def _name_set(scene: dict[str, Any]) -> set[str]:
    return {str(obj.get("name") or "") for obj in _objects(scene)}


def verify_transaction(
    receipt: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    assertions: dict[str, Any] | None = None,
) -> VerificationResult:
    """Verify a receipt against independent scene snapshots and explicit invariants."""
    assertions = assertions or {}
    passed: list[str] = []
    failed: list[str] = []

    if receipt.get("status") == "completed":
        passed.append("receipt completed")
    else:
        failed.append(f"receipt status is {receipt.get('status', 'missing')}")

    before_ids = {str(obj.get("id")) for obj in _objects(before)}
    after_ids = {str(obj.get("id")) for obj in _objects(after)}
    observed_created = after_ids - before_ids
    observed_deleted = before_ids - after_ids
    receipt_created = set(receipt.get("created_ids") or [])
    receipt_deleted = set(receipt.get("deleted_ids") or [])

    if receipt_created == observed_created:
        passed.append("created IDs match independent scene delta")
    else:
        failed.append(f"created ID mismatch receipt={sorted(receipt_created)} observed={sorted(observed_created)}")
    if receipt_deleted == observed_deleted:
        passed.append("deleted IDs match independent scene delta")
    else:
        failed.append(f"deleted ID mismatch receipt={sorted(receipt_deleted)} observed={sorted(observed_deleted)}")

    expected_delta = assertions.get("object_count_delta")
    if expected_delta is not None:
        actual_delta = len(after_ids) - len(before_ids)
        if actual_delta == int(expected_delta):
            passed.append(f"object count delta is {actual_delta}")
        else:
            failed.append(f"object count delta expected {expected_delta}, observed {actual_delta}")

    names = _name_set(after)
    for name in assertions.get("names_present", []):
        (passed if name in names else failed).append(
            f"name present: {name}" if name in names else f"missing required name: {name}"
        )
    for name in assertions.get("names_absent", []):
        (passed if name not in names else failed).append(
            f"name absent: {name}" if name not in names else f"unexpected name remains: {name}"
        )

    expected_units = assertions.get("units")
    if expected_units is not None:
        actual_units = (after.get("document") or {}).get("units")
        if str(actual_units).lower() == str(expected_units).lower():
            passed.append(f"units are {actual_units}")
        else:
            failed.append(f"units expected {expected_units}, observed {actual_units}")

    for key, expected in (assertions.get("numeric") or {}).items():
        actual: Any = after
        for part in key.split("."):
            actual = actual.get(part) if isinstance(actual, dict) else None
        tolerance = float(expected.get("tolerance", 0.0))
        target = float(expected["value"])
        if actual is not None and isclose(float(actual), target, abs_tol=tolerance):
            passed.append(f"{key} is within tolerance")
        else:
            failed.append(f"{key} expected {target} ± {tolerance}, observed {actual}")

    return VerificationResult(
        status="verified" if not failed else "failed",
        passed=tuple(passed),
        failed=tuple(failed),
        transaction_id=receipt.get("transaction_id"),
    )

