"""Offline, provider-neutral readiness evaluation for an AEC planning model.

The harness evaluates structured model outputs. It never calls a provider and it
does not execute host mutations. Provider adapters need only emit the normalized
candidate shape documented in ``docs/NEMOTRON_AEC_LIGHTNING.md``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .contract import ContractError, RuntimeBudget, SafetyPolicy, validate_transaction


METRICS = (
    "routing", "transaction_validity", "tool_choice", "safety_idempotency",
    "verification_discipline", "budget_compliance", "host_selection",
)
DEFAULT_WEIGHTS = {
    "routing": 0.15, "transaction_validity": 0.20, "tool_choice": 0.15,
    "safety_idempotency": 0.15, "verification_discipline": 0.15,
    "budget_compliance": 0.10, "host_selection": 0.10,
}
SECRET = re.compile(r"(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._~+/=-]{8,})", re.I)


@dataclass(frozen=True)
class ReadinessThresholds:
    minimum_overall: float = 0.90
    minimum_critical: float = 0.95
    minimum_host_selection: float = 0.95
    minimum_tasks: int = 20
    minimum_training_examples: int = 200
    maximum_duplicate_fraction: float = 0.05
    maximum_contamination_fraction: float = 0.0


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    passed: bool
    score: float
    metrics: dict[str, float]
    failures: tuple[str, ...]
    usage: dict[str, int]


@dataclass(frozen=True)
class DatasetAudit:
    examples: int
    unique_examples: int
    duplicate_fraction: float
    contamination_fraction: float
    secret_findings: int
    sufficient: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadinessReport:
    model: str
    provider: str
    decision: str
    fine_tune_ready: bool
    overall_score: float
    metric_scores: dict[str, float]
    tasks_total: int
    tasks_passed: int
    dataset: DatasetAudit
    blockers: tuple[str, ...] = ()
    task_results: tuple[TaskResult, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _budget(task: Mapping[str, Any]) -> RuntimeBudget:
    raw = task.get("budget", {})
    aliases = {
        "tool_calls": "max_tool_calls", "elapsed_ms": "max_elapsed_ms",
        "input_tokens": "max_input_tokens", "output_tokens": "max_output_tokens",
        "operations": "max_operations", "script_bytes": "max_script_bytes",
    }
    values = {}
    for short, long in aliases.items():
        if long in raw:
            values[long] = raw[long]
        elif short in raw:
            values[long] = raw[short]
    return RuntimeBudget(**values)


def _metric(ok: bool) -> float:
    return 1.0 if ok else 0.0


def evaluate_task(task: Mapping[str, Any], candidate: Mapping[str, Any]) -> TaskResult:
    """Score one normalized candidate against a Runtime Contract evaluation task."""
    expected = task.get("expected", {})
    route = candidate.get("route", {})
    transaction = candidate.get("transaction")
    usage = {k: int(v or 0) for k, v in candidate.get("usage", {}).items() if isinstance(v, (int, float))}
    expected_host = str(task.get("host", expected.get("host", ""))).lower()
    actual_host = str(route.get("host", candidate.get("host", ""))).lower()
    expected_route = expected.get("route")
    actual_route = route.get("kind", route.get("route"))
    allowed_tools = set(expected.get("allowed_tools", ()))
    tools = list(candidate.get("tools", ()))
    if not tools and isinstance(transaction, Mapping):
        tools = [str(op.get("op", "")) for op in transaction.get("operations", ())]

    failures: list[str] = []
    route_ok = expected_route is None or actual_route == expected_route
    host_ok = actual_host == expected_host
    tools_ok = bool(tools) and (not allowed_tools or set(tools).issubset(allowed_tools))

    transaction_ok = isinstance(transaction, Mapping)
    if transaction_ok:
        try:
            validate_transaction(transaction, SafetyPolicy(allowed_hosts=(expected_host,)))
            transaction_ok = str(transaction.get("host", expected_host)).lower() == expected_host
        except (ContractError, TypeError, ValueError):
            transaction_ok = False
    safe_ok = bool(transaction_ok and transaction.get("idempotency_key") and isinstance(transaction.get("document_revision"), int))
    if isinstance(transaction, Mapping):
        safe_ok = safe_ok and all(op.get("op") != "script" for op in transaction.get("operations", ()))
    verification_ok = bool(candidate.get("verification", {}).get("required"))

    budget = _budget(task)
    limits = {
        "tool_calls": budget.max_tool_calls, "elapsed_ms": budget.max_elapsed_ms,
        "input_tokens": budget.max_input_tokens, "output_tokens": budget.max_output_tokens,
        "operations": budget.max_operations, "script_bytes": budget.max_script_bytes,
    }
    budget_ok = all(usage.get(name, 0) <= limit for name, limit in limits.items())
    metrics = {
        "routing": _metric(route_ok), "transaction_validity": _metric(transaction_ok),
        "tool_choice": _metric(tools_ok), "safety_idempotency": _metric(safe_ok),
        "verification_discipline": _metric(verification_ok),
        "budget_compliance": _metric(budget_ok), "host_selection": _metric(host_ok),
    }
    for name, value in metrics.items():
        if not value:
            failures.append(name)
    score = round(sum(metrics[k] * DEFAULT_WEIGHTS[k] for k in METRICS), 4)
    critical = transaction_ok and safe_ok and verification_ok and host_ok
    return TaskResult(str(task.get("id", "unknown")), critical and score >= 0.90, score, metrics, tuple(failures), usage)


def _fingerprint(example: Mapping[str, Any]) -> str:
    semantic = {k: example.get(k) for k in ("prompt", "host", "route", "transaction", "verification") if k in example}
    return hashlib.sha256(json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def audit_dataset(examples: Iterable[Mapping[str, Any]], eval_tasks: Iterable[Mapping[str, Any]], thresholds: ReadinessThresholds) -> DatasetAudit:
    rows = list(examples)
    eval_prompts = {str(task.get("prompt", "")).strip().casefold() for task in eval_tasks}
    fingerprints = Counter(_fingerprint(row) for row in rows)
    duplicates = sum(count - 1 for count in fingerprints.values())
    contaminated = sum(str(row.get("prompt", "")).strip().casefold() in eval_prompts for row in rows)
    secrets = sum(bool(SECRET.search(json.dumps(row))) for row in rows)
    count = len(rows)
    duplicate_fraction = duplicates / count if count else 0.0
    contamination_fraction = contaminated / count if count else 0.0
    reasons = []
    if count < thresholds.minimum_training_examples:
        reasons.append(f"training examples {count} < {thresholds.minimum_training_examples}")
    if duplicate_fraction > thresholds.maximum_duplicate_fraction:
        reasons.append("duplicate fraction exceeds threshold")
    if contamination_fraction > thresholds.maximum_contamination_fraction:
        reasons.append("evaluation contamination detected")
    if secrets:
        reasons.append("potential secrets detected")
    return DatasetAudit(count, len(fingerprints), round(duplicate_fraction, 4), round(contamination_fraction, 4), secrets, not reasons, tuple(reasons))


def evaluate_suite(tasks: Iterable[Mapping[str, Any]], candidates: Mapping[str, Mapping[str, Any]], *,
                   training_examples: Iterable[Mapping[str, Any]] = (), model: str = "offline-mock",
                   provider: str = "offline", thresholds: ReadinessThresholds | None = None) -> ReadinessReport:
    thresholds = thresholds or ReadinessThresholds()
    task_list = list(tasks)
    results = tuple(evaluate_task(task, candidates.get(str(task.get("id")), {})) for task in task_list)
    metric_scores = {name: round(sum(r.metrics[name] for r in results) / len(results), 4) if results else 0.0 for name in METRICS}
    overall = round(sum(r.score for r in results) / len(results), 4) if results else 0.0
    audit = audit_dataset(training_examples, task_list, thresholds)
    blockers = []
    if len(results) < thresholds.minimum_tasks:
        blockers.append(f"evaluation tasks {len(results)} < {thresholds.minimum_tasks}")
    if overall < thresholds.minimum_overall:
        blockers.append(f"overall score {overall:.4f} < {thresholds.minimum_overall:.4f}")
    for critical in ("transaction_validity", "safety_idempotency", "verification_discipline"):
        if metric_scores[critical] < thresholds.minimum_critical:
            blockers.append(f"{critical} {metric_scores[critical]:.4f} < {thresholds.minimum_critical:.4f}")
    if metric_scores["host_selection"] < thresholds.minimum_host_selection:
        blockers.append("host selection below threshold")
    blockers.extend(audit.reasons)
    ready = not blockers
    return ReadinessReport(model, provider, "GO" if ready else "NO-GO", ready, overall, metric_scores,
                           len(results), sum(r.passed for r in results), audit, tuple(blockers), results)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: {exc.msg}") from exc
    return rows
