from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol


_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|cookie|password|secret|token)$", re.I)
_SECRET_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,})", re.I
)
_PATH = re.compile(r"(?:[A-Za-z]:\\|/home/|/Users/)[^\s\"']+")
_ALLOWED_TRACE_KEYS = frozenset(
    {"operation", "tool", "duration_ms", "success", "retry_count", "error_code", "host_revision"}
)


def _clean_text(value: str, limit: int = 512) -> str:
    value = _SECRET_VALUE.sub("[REDACTED]", value)
    value = _PATH.sub("[PATH]", value)
    return value[:limit]


def redact(value: Any) -> Any:
    """Deterministically sanitize structured data; raw conversations are never accepted."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key in sorted(value):
            if _SECRET_KEY.search(str(key)):
                clean[str(key)] = "[REDACTED]"
            elif str(key).lower() not in {"transcript", "messages", "prompt", "raw_request", "stdout", "stderr"}:
                clean[str(key)] = redact(value[key])
        return clean
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value[:100]]
    if isinstance(value, str):
        return _clean_text(value)
    return value if value is None or isinstance(value, (bool, int, float)) else _clean_text(str(value))


@dataclass(frozen=True)
class PromotionPolicy:
    promote_score: float = 0.85
    quarantine_score: float = 0.60
    maximum_duration_ms: float = 30_000.0
    require_verified: bool = True


@dataclass(frozen=True)
class MemoryOutcome:
    outcome_id: str
    project_id: str
    host: str
    transaction_id: str
    operation_signature: str
    status: str
    quality_score: float
    receipt: dict[str, Any]
    verification: dict[str, Any]
    trace_summary: tuple[dict[str, Any], ...] = ()
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _trace_summary(trace: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        redact({key: event[key] for key in sorted(event) if key in _ALLOWED_TRACE_KEYS})
        for event in list(trace)[:100]
    )


def _quality(receipt: dict[str, Any], verification: dict[str, Any], trace: tuple[dict[str, Any], ...], policy: PromotionPolicy) -> float:
    score = 0.0
    score += 0.35 if receipt.get("status") == "completed" else 0.0
    score += 0.40 if verification.get("status") == "verified" and not verification.get("failed") else 0.0
    attempted = int(receipt.get("actions_attempted", 0))
    completed = int(receipt.get("actions_completed", 0))
    score += 0.15 if attempted > 0 and attempted == completed else 0.0
    total_ms = sum(float(event.get("duration_ms", 0) or 0) for event in trace)
    score += 0.10 if total_ms <= policy.maximum_duration_ms else 0.0
    return round(score, 4)


def create_outcome(
    *, project_id: str, host: str, receipt: dict[str, Any], verification: dict[str, Any],
    trace: Iterable[dict[str, Any]] = (), operation_signature: str, policy: PromotionPolicy | None = None,
) -> MemoryOutcome:
    policy = policy or PromotionPolicy()
    safe_receipt = redact({
        key: receipt.get(key) for key in (
            "schema_version", "transaction_id", "status", "actions_attempted", "actions_completed",
            "created_ids", "deleted_ids", "error_code",
        ) if key in receipt
    })
    safe_verification = redact({
        key: verification.get(key) for key in ("schema_version", "status", "passed", "failed")
        if key in verification
    })
    safe_trace = _trace_summary(trace)
    score = _quality(safe_receipt, safe_verification, safe_trace, policy)
    verified = safe_verification.get("status") == "verified" and not safe_verification.get("failed")
    if safe_receipt.get("status") != "completed" or (policy.require_verified and not verified):
        state = "rejected"
    elif score >= policy.promote_score:
        state = "promoted"
    elif score >= policy.quarantine_score:
        state = "quarantined"
    else:
        state = "rejected"
    scope = {"project_id": project_id, "host": host.lower(), "operation_signature": operation_signature, "receipt": safe_receipt, "verification": safe_verification}
    digest = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return MemoryOutcome(
        outcome_id=digest, project_id=_clean_text(project_id, 128), host=_clean_text(host.lower(), 64),
        transaction_id=_clean_text(str(receipt.get("transaction_id", "")), 128),
        operation_signature=_clean_text(operation_signature, 256), status=state, quality_score=score,
        receipt=safe_receipt, verification=safe_verification, trace_summary=safe_trace,
    )


class DMLAdapter(Protocol):
    def put(self, outcome: MemoryOutcome) -> bool: ...
    def get(self, project_id: str, host: str, outcome_id: str) -> MemoryOutcome | None: ...
    def list(self, project_id: str, host: str, status: str | None = None) -> list[MemoryOutcome]: ...


class MemoryDMLAdapter:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], MemoryOutcome] = {}

    def put(self, outcome: MemoryOutcome) -> bool:
        key = (outcome.project_id, outcome.host, outcome.outcome_id)
        is_new = key not in self._items
        self._items[key] = outcome
        return is_new

    def get(self, project_id: str, host: str, outcome_id: str) -> MemoryOutcome | None:
        return self._items.get((project_id, host.lower(), outcome_id))

    def list(self, project_id: str, host: str, status: str | None = None) -> list[MemoryOutcome]:
        values = [item for (project, item_host, _), item in self._items.items() if project == project_id and item_host == host.lower()]
        return sorted((item for item in values if status is None or item.status == status), key=lambda item: item.outcome_id)


class FilesystemDMLAdapter(MemoryDMLAdapter):
    """Local reference adapter. Files contain only sanitized MemoryOutcome records."""
    def __init__(self, root: str | Path) -> None:
        super().__init__()
        self.root = Path(root)

    def _scope(self, project_id: str, host: str) -> Path:
        scope = hashlib.sha256(f"{project_id}\0{host.lower()}".encode()).hexdigest()[:20]
        return self.root / scope

    def _path(self, outcome: MemoryOutcome) -> Path:
        return self._scope(outcome.project_id, outcome.host) / f"{outcome.outcome_id}.json"

    @staticmethod
    def _decode(path: Path) -> MemoryOutcome:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["trace_summary"] = tuple(data.get("trace_summary", ()))
        return MemoryOutcome(**data)

    def put(self, outcome: MemoryOutcome) -> bool:
        path = self._path(outcome)
        is_new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(outcome.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
        super().put(outcome)
        return is_new

    def get(self, project_id: str, host: str, outcome_id: str) -> MemoryOutcome | None:
        cached = super().get(project_id, host, outcome_id)
        if cached is not None:
            return cached
        path = self._scope(project_id, host) / f"{outcome_id}.json"
        return self._decode(path) if path.is_file() else None

    def list(self, project_id: str, host: str, status: str | None = None) -> list[MemoryOutcome]:
        scope = self._scope(project_id, host)
        values = [self._decode(path) for path in scope.glob("*.json")] if scope.is_dir() else []
        return sorted((item for item in values if status is None or item.status == status), key=lambda item: item.outcome_id)
