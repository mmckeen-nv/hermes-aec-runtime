from __future__ import annotations

import asyncio

import pytest

from hermes_aec_runtime.observability import (
    ExecutionBudget, RunMetrics, bounded_stage, correlation_id, readiness,
)


def test_budgets_are_finite_and_capped():
    assert ExecutionBudget(query_seconds=1).query_seconds == 1
    for value in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            ExecutionBudget(query_seconds=value)
    with pytest.raises(ValueError, match="safety cap"):
        ExecutionBudget(total_seconds=301)
    with pytest.raises(ValueError, match="unsupported"):
        ExecutionBudget.from_mapping({"api_key": "sk-never-echo-this"})


def test_correlation_ids_are_opaque_not_secret_bearing_text():
    assert correlation_id("demo:run-42") == "demo:run-42"
    assert len(correlation_id()) == 32
    with pytest.raises(ValueError):
        correlation_id("Bearer secret token")


def test_bounded_stage_records_success_and_timeout_without_error_text():
    metrics = RunMetrics(trace_id="trace-1")

    async def work():
        return 7
    assert asyncio.run(bounded_stage(metrics, "query", 1, work())) == 7

    async def slow():
        await asyncio.sleep(.05)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(bounded_stage(metrics, "mutation", .001, slow()))
    snapshot = metrics.snapshot()
    assert [stage["status"] for stage in snapshot["stages"]] == ["completed", "timeout"]
    assert snapshot["stages"][1]["error_code"] == "TimeoutError"
    assert "secret" not in str(snapshot)


def test_readiness_is_concurrent_bounded_and_never_returns_exception_messages():
    async def okay(): return {"api_key": "sk-never-return"}
    async def broken(): raise RuntimeError("sk-super-secret-value")
    result = asyncio.run(readiness({"runtime": okay, "host": broken}, timeout_seconds=.1))
    assert result["status"] == "not_ready"
    assert result["components"]["runtime"]["status"] == "ready"
    assert result["components"]["host"]["error_code"] == "RuntimeError"
    assert "secret" not in str(result).lower()
