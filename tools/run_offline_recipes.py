#!/usr/bin/env python3
"""Compile and validate the documented recipes without Rhino or Blender running."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hermes_aec_runtime.blender import recovery_plan, validate_handoff_manifest
from hermes_aec_runtime.blender_operations import compile_blender_transaction
from hermes_aec_runtime.flight_recorder import make_trace
from hermes_aec_runtime.memory import create_outcome
from hermes_aec_runtime.model_eval import evaluate_task
from hermes_aec_runtime.operations import compile_transaction


def validate_recipe(recipe: dict) -> dict:
    kind = recipe["kind"]
    if kind == "rhino_operations":
        compiled = compile_transaction(recipe["operations"])
        return {"fingerprint": compiled.fingerprint, "operations": len(compiled.normalized["operations"]), "script_bytes": len(compiled.script.encode())}
    if kind == "blender_operations":
        compiled = compile_blender_transaction(recipe["operations"])
        return {"fingerprint": compiled.fingerprint, "operations": len(compiled.normalized["operations"]), "script_bytes": len(compiled.script.encode())}
    if kind == "handoff_manifest":
        result = validate_handoff_manifest(recipe["manifest"])
        if not result["valid"]:
            raise ValueError("invalid handoff: " + "; ".join(result["errors"]))
        return result
    if kind == "recovery":
        result = recovery_plan(recipe["receipt"])
        if result["action"] != recipe["expected_action"]:
            raise ValueError(f"expected {recipe['expected_action']}, got {result['action']}")
        return result
    if kind == "workflow_memory":
        result = create_outcome(project_id=recipe["project_id"], host=recipe["host"], receipt=recipe["receipt"], verification=recipe["verification"], trace=recipe["trace"], operation_signature=recipe["operation_signature"])
        if result.status != recipe["expected_status"]:
            raise ValueError(f"expected {recipe['expected_status']}, got {result.status}")
        return {"status": result.status, "quality_score": result.quality_score, "outcome_id": result.outcome_id}
    if kind == "flight_recorder":
        fields = {key: recipe[key] for key in ("request", "route", "scene_subset", "transaction", "timing", "tool_outcomes", "receipt", "verification")}
        result = make_trace(**fields, created_at=0)
        if not result["training_quality"]["accepted"]:
            raise ValueError("trace rejected: " + ", ".join(result["training_quality"]["reasons"]))
        return {"trace_id": result["trace_id"], "training_quality": result["training_quality"]}
    if kind == "model_evaluation":
        result = evaluate_task(recipe["task"], recipe["candidate"])
        if result.passed is not recipe["expected_passed"]:
            raise ValueError(f"expected passed={recipe['expected_passed']}, got {result.passed}")
        return {"passed": result.passed, "score": result.score, "failures": list(result.failures)}
    raise ValueError(f"unsupported recipe kind: {kind}")


def run(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "aec-offline-recipes/1.0":
        raise ValueError("unsupported recipe document")
    return [{"id": recipe["id"], "kind": recipe["kind"], **validate_recipe(recipe), "validation": "valid"} for recipe in document["recipes"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes", type=Path, default=ROOT / "examples" / "offline_recipes.json")
    args = parser.parse_args()
    results = run(args.recipes)
    print(json.dumps({"status": "passed", "recipes": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
