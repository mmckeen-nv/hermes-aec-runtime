"""Bounded, privacy-safe workflow metrics and readiness primitives."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import math
import re
from pathlib import Path
from time import perf_counter
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4

from .memory import redact

_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def correlation_id(value: str | None = None) -> str:
    """Return an opaque safe correlation ID; never accept arbitrary user text."""
    if value is None:
        return uuid4().hex
    if not _CORRELATION_ID.fullmatch(value):
        raise ValueError("correlation_id must be 1-128 opaque ASCII identifier characters")
    return value


@dataclass(frozen=True)
class ExecutionBudget:
    """Wall-clock limits for a one-call workflow.

    Limits are intentionally finite and capped. A caller may tighten them but
    cannot turn the sidecar into an unbounded job runner.
    """

    query_seconds: float = 30.0
    mutation_seconds: float = 90.0
    verification_seconds: float = 30.0
    total_seconds: float = 150.0

    def __post_init__(self) -> None:
        values = (self.query_seconds, self.mutation_seconds, self.verification_seconds, self.total_seconds)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("workflow budgets must be finite positive seconds")
        if self.total_seconds > 300 or max(values[:-1]) > 180:
            raise ValueError("workflow budget exceeds the runtime safety cap")

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ExecutionBudget":
        supplied = dict(value or {})
        allowed = {"query_seconds", "mutation_seconds", "verification_seconds", "total_seconds"}
        if not supplied.keys() <= allowed:
            raise ValueError("budget contains unsupported fields")
        return cls(**supplied)


@dataclass
class RunMetrics:
    """Per-run metrics; contains no request, scene, credential, or error text."""

    trace_id: str = field(default_factory=correlation_id)
    started: float = field(default_factory=perf_counter, repr=False)
    stages: list[dict[str, Any]] = field(default_factory=list)

    def record(self, stage: str, started: float, budget_seconds: float, status: str, error: BaseException | None = None) -> None:
        self.stages.append({
            "stage": stage,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "budget_ms": round(budget_seconds * 1000, 3),
            "status": status,
            # Exception class is actionable and cannot contain a secret-bearing message.
            "error_code": type(error).__name__ if error is not None else None,
        })

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "aec-workflow-metrics/1.0",
            "trace_id": self.trace_id,
            "total_ms": round((perf_counter() - self.started) * 1000, 3),
            "stages": [dict(item) for item in self.stages],
        }


async def bounded_stage(
    metrics: RunMetrics, stage: str, budget_seconds: float, awaitable: Awaitable[Any],
) -> Any:
    """Await a stage under a hard deadline and always emit one metric."""
    started = perf_counter()
    try:
        result = await asyncio.wait_for(awaitable, timeout=budget_seconds)
    except asyncio.TimeoutError as exc:
        metrics.record(stage, started, budget_seconds, "timeout", exc)
        raise
    except Exception as exc:
        metrics.record(stage, started, budget_seconds, "failed", exc)
        raise
    metrics.record(stage, started, budget_seconds, "completed")
    return result


async def readiness(
    components: Mapping[str, Callable[[], Awaitable[Any]]], *, timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Probe dependencies concurrently without returning payloads or exception text."""
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
        raise ValueError("readiness timeout must be between 0 and 30 seconds")

    async def probe(name: str, callback: Callable[[], Awaitable[Any]]) -> tuple[str, dict[str, Any]]:
        started = perf_counter()
        try:
            await asyncio.wait_for(callback(), timeout_seconds)
            value = {"status": "ready", "latency_ms": round((perf_counter() - started) * 1000, 3)}
        except asyncio.TimeoutError:
            value = {"status": "unavailable", "latency_ms": round((perf_counter() - started) * 1000, 3), "error_code": "TimeoutError"}
        except Exception as exc:
            value = {"status": "unavailable", "latency_ms": round((perf_counter() - started) * 1000, 3), "error_code": type(exc).__name__}
        return name, value

    results = dict(await asyncio.gather(*(probe(name, callback) for name, callback in sorted(components.items()))))
    return {
        "schema_version": "aec-runtime-health/1.0",
        "status": "ready" if results and all(item["status"] == "ready" for item in results.values()) else "not_ready",
        "components": redact(results),
    }


def storage_ready(path: str | Path) -> bool:
    """Check configuration and existing permissions without creating test residue."""
    target = Path(path)
    parent = target.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return parent.is_dir()
