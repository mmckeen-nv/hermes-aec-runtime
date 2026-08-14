"""Privacy-safe, append-only execution traces for evaluation and training."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Iterable, Mapping

from .contract import canonical_json
from .memory import redact

TRACE_SCHEMA = "aec-flight-trace/1.0"
EXPORT_SCHEMA = "aec-tool-example/1.0"
_DENIED_KEYS = re.compile(r"^(?:messages?|transcript|conversation|stdout|stderr|raw(?:_request|_scene|_response)?)$", re.I)
_TRANSCRIPT_KEYS = re.compile(r"^(?:messages?|transcript|conversation|raw(?:_request|_response)?)$", re.I)
_lock = threading.Lock()


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _safe(value: Any, _seen: set[int] | None = None) -> Any:
    """Redact secrets and paths, and reject transcript-shaped fields recursively."""
    _seen = set() if _seen is None else _seen
    if isinstance(value, (Mapping, list, tuple)):
        marker = id(value)
        if marker in _seen:
            return "[CYCLE]"
        _seen.add(marker)
    if isinstance(value, Mapping):
        result = redact({str(k): _safe(v, _seen) for k, v in value.items() if not _DENIED_KEYS.match(str(k))})
        _seen.remove(id(value))
        return result
    if isinstance(value, (list, tuple)):
        result = [_safe(v, _seen) for v in value[:1000]]
        _seen.remove(id(value))
        return result
    return redact(value)


def _contains_transcript(value: Any, _seen: set[int] | None = None) -> bool:
    _seen = set() if _seen is None else _seen
    if isinstance(value, (Mapping, list, tuple)):
        marker = id(value)
        if marker in _seen:
            return False
        _seen.add(marker)
    if isinstance(value, Mapping):
        result = any(_TRANSCRIPT_KEYS.match(str(k)) or _contains_transcript(v, _seen) for k, v in value.items())
        _seen.remove(id(value))
        return result
    if isinstance(value, (list, tuple)):
        result = any(_contains_transcript(v, _seen) for v in value)
        _seen.remove(id(value))
        return result
    return False


def scene_subset_digest(scene_subset: Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Describe a focused scene subset without retaining its potentially huge contents."""
    safe = _safe(scene_subset)
    count = len(safe) if isinstance(safe, list) else len(safe.get("objects", ())) if isinstance(safe, dict) else 0
    return {"content_hash": _digest(safe), "object_count": count}


@dataclass(frozen=True)
class TrainingGate:
    require_completed: bool = True
    require_verified: bool = True
    require_typed_transaction: bool = True
    allow_recovery: bool = True


def assess_training_quality(trace: Mapping[str, Any], gate: TrainingGate = TrainingGate()) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    receipt = trace.get("receipt") or {}
    verification = trace.get("verification") or {}
    transaction = trace.get("transaction") or {}
    state = receipt.get("state", receipt.get("status"))
    verified = verification.get("status") in {"verified", "passed"} and not verification.get("failed")
    operations = transaction.get("operations") or []
    if gate.require_completed and state != "completed": reasons.append("receipt_not_completed")
    if gate.require_verified and not verified: reasons.append("outcome_not_verified")
    if gate.require_typed_transaction and (not operations or any(op.get("op") == "script" for op in operations if isinstance(op, Mapping))):
        reasons.append("typed_transaction_required")
    if not gate.allow_recovery and trace.get("recovery"): reasons.append("recovery_not_allowed")
    if _contains_transcript(trace): reasons.append("raw_transcript_present")
    if not trace.get("request") or not trace.get("route"): reasons.append("request_and_route_required")
    return not reasons, tuple(reasons)


def make_trace(
    *, request: str, route: Mapping[str, Any], scene_subset: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    transaction: Mapping[str, Any], timing: Mapping[str, Any], tool_outcomes: Iterable[Mapping[str, Any]],
    receipt: Mapping[str, Any], verification: Mapping[str, Any], recovery: Mapping[str, Any] | None = None,
    model: Mapping[str, Any] | None = None, token_usage: Mapping[str, Any] | None = None,
    created_at: int | None = None, gate: TrainingGate = TrainingGate(),
) -> dict[str, Any]:
    supplied = {
        "schema_version": TRACE_SCHEMA, "created_at": int(time.time() * 1000) if created_at is None else created_at,
        "request": request, "route": route, "scene_subset": scene_subset_digest(scene_subset),
        "transaction": transaction, "timing": timing, "tool_outcomes": list(tool_outcomes),
        "receipt": receipt, "verification": verification, "recovery": recovery or {},
        "model": model or {}, "token_usage": token_usage or {},
    }
    if _contains_transcript(supplied):
        raise ValueError("raw transcripts/messages are forbidden in Flight Recorder traces")
    body = _safe(supplied)
    # Identity excludes wall-clock creation time, so deterministic replays deduplicate.
    identity = {key: value for key, value in body.items() if key != "created_at"}
    body["trace_id"] = _digest(identity)
    accepted, reasons = assess_training_quality(body, gate)
    body["training_quality"] = {"accepted": accepted, "reasons": list(reasons)}
    return body


class FlightRecorder:
    """A local JSONL journal. Each line is complete, flushed and fsynced before return."""
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _known_ids(self) -> set[str]:
        if not self.path.exists(): return set()
        ids: set[str] = set()
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                try: ids.add(json.loads(line)["trace_id"])
                except (json.JSONDecodeError, KeyError): continue  # ignore an interrupted final line
        return ids

    def append(self, trace: Mapping[str, Any]) -> bool:
        if _contains_transcript(trace):
            raise ValueError("raw transcripts/messages are forbidden in Flight Recorder traces")
        safe = _safe(trace)
        if safe.get("schema_version") != TRACE_SCHEMA or not safe.get("trace_id"):
            raise ValueError("trace must be created by make_trace")
        encoded = (canonical_json(safe) + "\n").encode("utf-8")
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if safe["trace_id"] in self._known_ids(): return False
            fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally: os.close(fd)
        return True

    def read(self) -> Iterable[dict[str, Any]]:
        if not self.path.exists(): return
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                try: yield json.loads(line)
                except json.JSONDecodeError: continue


def export_training_examples(source: str | Path, destination: str | Path) -> dict[str, int]:
    """Export only verified typed outcomes; never emit raw transcripts or rejected traces."""
    recorder = FlightRecorder(source)
    accepted: dict[str, dict[str, Any]] = {}
    rejected = 0
    for trace in recorder.read():
        okay, _ = assess_training_quality(trace)
        if not okay or not trace.get("training_quality", {}).get("accepted"):
            rejected += 1
            continue
        example = _safe({
            "schema_version": EXPORT_SCHEMA, "request": trace["request"], "route": trace["route"],
            "scene_subset": trace["scene_subset"], "tool_call": trace["transaction"],
            "tool_result": trace["receipt"], "verification": trace["verification"],
            "model": trace.get("model", {}), "token_usage": trace.get("token_usage", {}),
            "source_trace_id": trace["trace_id"],
        })
        accepted[_digest(example)] = example
    target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for key in sorted(accepted): stream.write(canonical_json(accepted[key]) + "\n")
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, target)
    return {"accepted": len(accepted), "rejected": rejected}
