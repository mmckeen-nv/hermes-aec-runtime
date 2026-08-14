from __future__ import annotations

import asyncio

from benchmarks.run_workflow import percentile, run


def test_percentile_is_deterministic_for_short_samples():
    assert percentile([9, 1, 5, 3], .5) == 3
    assert percentile([9, 1, 5, 3], .95) == 5


def test_one_call_benchmark_checks_correctness_and_budget():
    result = asyncio.run(run(10, max_p95_ms=100))
    assert result["status"] == "passed"
    assert result["iterations"] == 10
    assert result["p95_ms"] <= result["budget_p95_ms"]
