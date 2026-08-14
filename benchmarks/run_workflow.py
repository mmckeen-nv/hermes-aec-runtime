"""Benchmark the complete one-call workflow without contacting a CAD host."""
from __future__ import annotations

import argparse
import asyncio
import json
from statistics import mean
from time import perf_counter

from hermes_aec_runtime.observability import ExecutionBudget
from hermes_aec_runtime.orchestrator import WorkflowOrchestrator


class BenchmarkGateway:
    def __init__(self) -> None:
        self.objects = [{"id": "pool", "name": "Pool", "kind": "surface", "layer": "Site"}]

    async def query(self, query: dict) -> dict:
        return {"host": "rhino", "document_revision": "benchmark:1", "objects": list(self.objects)}

    async def execute_typed(self, **kwargs) -> dict:
        self.objects.append({"id": "fence", "name": "Pool Fence", "kind": "curve", "layer": "Site"})
        return {"status": "completed", "transaction_id": kwargs["idempotency_key"], "created_ids": ["fence"], "deleted_ids": []}


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))]


async def run(iterations: int, max_p95_ms: float) -> dict:
    durations: list[float] = []
    for index in range(iterations):
        gateway = BenchmarkGateway()
        started = perf_counter()
        result = await WorkflowOrchestrator({"rhino": gateway}).run(
            request="Add a fence around the pool",
            operations=[{"op": "create_line", "start": [0, 0, 0], "end": [1, 0, 0]}],
            idempotency_key=f"benchmark:{index}", correlation_id=f"benchmark:{index}",
            assertions={"object_count_delta": 1, "names_present": ["Pool Fence"]},
            budget=ExecutionBudget(query_seconds=1, mutation_seconds=1, verification_seconds=1, total_seconds=3),
        )
        if result.status != "verified" or len(result.metrics["stages"]) != 3:
            raise RuntimeError("one-call workflow benchmark failed correctness checks")
        durations.append((perf_counter() - started) * 1000)
    p95 = percentile(durations, .95)
    return {
        "schema_version": "aec-workflow-benchmark/1.0", "mode": "mock-one-call",
        "iterations": iterations, "mean_ms": round(mean(durations), 3),
        "p50_ms": round(percentile(durations, .50), 3), "p95_ms": round(p95, 3),
        "p99_ms": round(percentile(durations, .99), 3), "max_ms": round(max(durations), 3),
        "budget_p95_ms": max_p95_ms, "status": "passed" if p95 <= max_p95_ms else "failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--max-p95-ms", type=float, default=10.0)
    args = parser.parse_args()
    if args.iterations < 1 or args.max_p95_ms <= 0:
        parser.error("iterations and max-p95-ms must be positive")
    result = asyncio.run(run(args.iterations, args.max_p95_ms))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
