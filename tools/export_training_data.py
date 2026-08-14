#!/usr/bin/env python3
"""Export accepted Flight Recorder traces for tool-calling SFT and evals."""
from __future__ import annotations
import argparse
import json
from hermes_aec_runtime.flight_recorder import export_training_examples

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="append-only Flight Recorder JSONL")
    parser.add_argument("destination", help="output tool-example JSONL")
    args = parser.parse_args()
    print(json.dumps(export_training_examples(args.source, args.destination), sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
