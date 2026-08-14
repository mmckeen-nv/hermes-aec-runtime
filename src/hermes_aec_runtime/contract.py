"""Dependency-free AEC Runtime Contract v1 validation and lifecycle helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import time
from typing import Any, Mapping

CONTRACT_VERSION = "1.0.0"
SCHEMA_BASE = "https://mmckeen-nv.github.io/hermes-aec-runtime/schemas"


class ContractError(ValueError):
    """Raised when a contract invariant is violated."""


class TransactionState(str, Enum):
    PLANNED = "planned"
    VALIDATED = "validated"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    ROLLED_BACK = "rolled_back"


_TRANSITIONS = {
    TransactionState.PLANNED: {TransactionState.VALIDATED, TransactionState.FAILED},
    TransactionState.VALIDATED: {TransactionState.EXECUTING, TransactionState.FAILED},
    TransactionState.EXECUTING: {TransactionState.COMPLETED, TransactionState.FAILED, TransactionState.UNKNOWN},
    TransactionState.UNKNOWN: {TransactionState.COMPLETED, TransactionState.FAILED, TransactionState.ROLLED_BACK},
    TransactionState.FAILED: {TransactionState.ROLLED_BACK},
    TransactionState.COMPLETED: set(),
    TransactionState.ROLLED_BACK: set(),
}


@dataclass(frozen=True)
class RuntimeBudget:
    max_tool_calls: int = 8
    max_elapsed_ms: int = 120_000
    max_input_tokens: int = 64_000
    max_output_tokens: int = 8_192
    max_operations: int = 64
    max_script_bytes: int = 65_536

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if not isinstance(value, int) or value <= 0:
                raise ContractError(f"{key} must be a positive integer")


@dataclass
class BudgetUsage:
    tool_calls: int = 0
    elapsed_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    operations: int = 0
    script_bytes: int = 0

    def charge(self, budget: RuntimeBudget, **amounts: int) -> None:
        unknown = set(amounts) - set(asdict(self))
        if unknown:
            raise ContractError(f"unknown budget counters: {sorted(unknown)}")
        for name, amount in amounts.items():
            if not isinstance(amount, int) or amount < 0:
                raise ContractError(f"{name} charge must be a non-negative integer")
            setattr(self, name, getattr(self, name) + amount)
        self.enforce(budget)

    def enforce(self, budget: RuntimeBudget) -> None:
        limits = {
            "tool_calls": budget.max_tool_calls, "elapsed_ms": budget.max_elapsed_ms,
            "input_tokens": budget.max_input_tokens, "output_tokens": budget.max_output_tokens,
            "operations": budget.max_operations, "script_bytes": budget.max_script_bytes,
        }
        exceeded = {k: (getattr(self, k), v) for k, v in limits.items() if getattr(self, k) > v}
        if exceeded:
            raise ContractError("budget exceeded: " + ", ".join(f"{k}={a}>{b}" for k, (a, b) in exceeded.items()))


@dataclass(frozen=True)
class SafetyPolicy:
    mutation_requires_revision: bool = True
    mutation_requires_idempotency_key: bool = True
    rollback_on_failure: bool = True
    permit_arbitrary_script: bool = False
    require_verification: bool = True
    allowed_hosts: tuple[str, ...] = ("rhino", "blender", "freecad")


def transition(current: str | TransactionState, target: str | TransactionState) -> TransactionState:
    try:
        source, destination = TransactionState(current), TransactionState(target)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    if destination not in _TRANSITIONS[source]:
        raise ContractError(f"illegal transaction transition: {source.value} -> {destination.value}")
    return destination


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_envelope(document: Mapping[str, Any], kind: str) -> None:
    required = ("schema_version", "kind", "id", "created_at")
    missing = [name for name in required if name not in document]
    if missing:
        raise ContractError(f"missing envelope fields: {', '.join(missing)}")
    if not document["id"] or not document["kind"]:
        raise ContractError("envelope id and kind must be non-empty")
    if not isinstance(document["created_at"], int) or document["created_at"] < 0:
        raise ContractError("created_at must be a non-negative integer")
    if document["schema_version"] != CONTRACT_VERSION:
        raise ContractError(f"unsupported schema_version {document['schema_version']!r}; expected {CONTRACT_VERSION}")
    if document["kind"] != kind:
        raise ContractError(f"expected kind {kind!r}, got {document['kind']!r}")


def validate_transaction(document: Mapping[str, Any], policy: SafetyPolicy = SafetyPolicy()) -> None:
    validate_envelope(document, "operation_transaction")
    operations = document.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ContractError("operations must be a non-empty list")
    if policy.mutation_requires_revision and not isinstance(document.get("document_revision"), int):
        raise ContractError("document_revision is required for mutation")
    if policy.mutation_requires_idempotency_key and not document.get("idempotency_key"):
        raise ContractError("idempotency_key is required for mutation")
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping) or not operation.get("op"):
            raise ContractError(f"operations[{index}].op is required")
        if operation.get("op") == "script" and not policy.permit_arbitrary_script:
            raise ContractError("arbitrary script operation is forbidden by safety policy")


def validate_receipt(document: Mapping[str, Any]) -> None:
    validate_envelope(document, "execution_receipt")
    if document.get("state") not in {state.value for state in TransactionState}:
        raise ContractError("receipt state is invalid")
    if not document.get("transaction_id"):
        raise ContractError("transaction_id is required")


def make_envelope(kind: str, identifier: str, **payload: Any) -> dict[str, Any]:
    return {"schema_version": CONTRACT_VERSION, "kind": kind, "id": identifier,
            "created_at": int(time.time() * 1000), **payload}


def assert_compatible(producer: str, consumer: str = CONTRACT_VERSION) -> None:
    """v1 policy: same major accepted; producer minor must not exceed consumer minor."""
    try:
        p, c = tuple(map(int, producer.split("."))), tuple(map(int, consumer.split(".")))
    except Exception as exc:
        raise ContractError("versions must be MAJOR.MINOR.PATCH") from exc
    if len(p) != 3 or len(c) != 3 or p[0] != c[0] or p[1] > c[1]:
        raise ContractError(f"incompatible contract versions producer={producer}, consumer={consumer}")
