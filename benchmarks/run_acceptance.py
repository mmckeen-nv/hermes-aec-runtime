"""Run a small, reproducible sidecar benchmark.

Mock mode is the default and never contacts Rhino. Live mode is read-only and
requires both ``--live`` and ``HERMES_AEC_ALLOW_LIVE=1``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from time import perf_counter

from hermes_aec_runtime.operations import compile_transaction
from hermes_aec_runtime.rhino import RhinoClient
from hermes_aec_runtime.scene_index import SCENE_SCHEMA_VERSION, SceneIndex
from hermes_aec_runtime.verification import verify_transaction


def _scene(objects: list[dict]) -> dict:
    return {
        "schema_version": SCENE_SCHEMA_VERSION,
        "document_revision": "mock:1",
        "document": {"units": "Meters"},
        "units": "Meters",
        "tolerance": 0.001,
        "layers": ["AEC::Site"],
        "relationships": [],
        "objects": objects,
    }


def run_mock(iterations: int) -> dict:
    durations: list[float] = []
    for _ in range(iterations):
        started = perf_counter()
        before = _scene([{
            "id": "house", "name": "Cliff House", "kind": "Brep",
            "layer": "AEC::Building", "visible": True, "locked": False,
            "bounds": {"min": [0, 0, 0], "max": [31, 34, 15.4]},
        }])
        selected = SceneIndex(before).query(name="Cliff*")
        compiled = compile_transaction([
            {"op": "create_box", "id": "probe", "min": [40, 40, 0], "max": [41, 41, 1]},
            {"op": "set_attributes", "targets": ["$probe"], "name": "AEC Acceptance Probe"},
            {"op": "delete", "targets": ["$probe"]},
        ])
        after = _scene(list(before["objects"]))
        receipt = {
            "status": "completed", "transaction_id": compiled.fingerprint,
            "created_ids": [], "deleted_ids": [],
        }
        verified = verify_transaction(receipt, before, after, {
            "object_count_delta": 0, "names_absent": ["AEC Acceptance Probe"],
        })
        if len(selected) != 1 or verified.status != "verified":
            raise RuntimeError("mock acceptance flow failed")
        durations.append((perf_counter() - started) * 1000)
    return {
        "mode": "mock", "iterations": iterations, "status": "passed",
        "mean_ms": round(sum(durations) / len(durations), 3),
        "min_ms": round(min(durations), 3), "max_ms": round(max(durations), 3),
        "zero_residue": True,
    }


async def run_live() -> dict:
    started = perf_counter()
    client = RhinoClient()
    health = await client.health()
    if health.get("status") != "healthy":
        raise RuntimeError(health.get("error", "Rhino MCP is unavailable"))
    scene = await client.scene_index(limit=100)
    return {
        "mode": "live-read-only", "status": "passed",
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        "objects_sampled": scene.get("count", 0), "health": health,
        "mutations": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--live", action="store_true", help="run a read-only Rhino probe")
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    if args.live:
        if os.environ.get("HERMES_AEC_ALLOW_LIVE") != "1":
            parser.error("live mode requires HERMES_AEC_ALLOW_LIVE=1")
        result = asyncio.run(run_live())
    else:
        result = run_mock(args.iterations)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
