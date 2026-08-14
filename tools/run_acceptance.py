from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from hermes_aec_runtime.acceptance import run_deterministic_acceptance, run_live_rhino_acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes AEC end-to-end acceptance harness")
    parser.add_argument("--output", type=Path, default=Path(".runtime/acceptance"))
    parser.add_argument("--live-rhino", action="store_true", help="opt in to one reversible live Rhino mutation")
    parser.add_argument("--confirm", default="", help="required exact confirmation phrase for live mutation")
    args = parser.parse_args()
    result = asyncio.run(run_live_rhino_acceptance(confirmation=args.confirm)) if args.live_rhino else asyncio.run(run_deterministic_acceptance(args.output))
    print(json.dumps(result, indent=2))
    if not result["passed"]: raise SystemExit(1)


if __name__ == "__main__": main()
