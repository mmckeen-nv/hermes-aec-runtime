#!/usr/bin/env python3
"""Evaluate normalized AEC model outputs without contacting a provider."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hermes_aec_runtime.model_eval import ReadinessThresholds, evaluate_suite, load_jsonl


def _load(path: Path):
    if path.suffix == ".jsonl":
        return load_jsonl(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else value.get("items", [])


def _mock(task):
    expected = task["expected"]
    host = task["host"]
    op = expected["allowed_tools"][0]
    return {
        "route": {"kind": expected["route"], "host": host},
        "host": host,
        "tools": [op],
        "transaction": {
            "schema_version": "1.0.0", "kind": "operation_transaction",
            "id": f"tx-{task['id']}", "created_at": 0, "host": host,
            "document_revision": 1, "idempotency_key": f"eval-{task['id']}",
            "operations": [{"op": op}],
        },
        "verification": {"required": True},
        "usage": {"tool_calls": 3, "elapsed_ms": 100, "input_tokens": 500,
                  "output_tokens": 100, "operations": 1, "script_bytes": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline AEC model readiness evaluator")
    parser.add_argument("--tasks", type=Path, default=ROOT / "evals" / "baseline_tasks.json")
    parser.add_argument("--candidates", type=Path, help="JSON/JSONL normalized candidate outputs")
    parser.add_argument("--training", type=Path, help="Flight Recorder JSON/JSONL promoted examples")
    parser.add_argument("--mock", action="store_true", help="use deterministic reference candidates")
    parser.add_argument("--model", default="offline-mock")
    parser.add_argument("--provider", default="offline")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    tasks = _load(args.tasks)
    if args.mock:
        candidates = {task["id"]: _mock(task) for task in tasks}
    elif args.candidates:
        candidates = {row["task_id"]: row.get("candidate", row) for row in _load(args.candidates)}
    else:
        parser.error("provide --mock or --candidates")
    training = _load(args.training) if args.training else []
    report = evaluate_suite(tasks, candidates, training_examples=training, model=args.model,
                            provider=args.provider, thresholds=ReadinessThresholds())
    output = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report.fine_tune_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
