from __future__ import annotations

import argparse
import json

from .runtime import assemble_transaction, execute_transaction, preprocess_scene, route_context


def demo() -> dict:
    scene = preprocess_scene({
        "document_id": "demo", "host": "mock", "units": "meters",
        "objects": [
            {"id": "pool-1", "name": "Swimming Pool", "kind": "closed_curve", "layer": "Site::Pool"},
            {"id": "house-1", "name": "Cliff House", "kind": "building", "layer": "Architecture"},
        ],
    })
    routed = route_context("put a safety fence around the pool", scene)
    tx = assemble_transaction(
        "put a safety fence around the pool", "mock", "create_pool_fence",
        [obj.id for obj in routed], {"height": 1.2, "offset": 1.0}, dry_run=False,
    )
    return {"scene": scene.to_dict(), "transaction": tx.to_dict(), "receipt": execute_transaction(tx).to_dict()}


def main() -> None:
    parser = argparse.ArgumentParser(prog="hermes-aec")
    parser.add_argument("command", choices=("doctor", "demo"))
    args = parser.parse_args()
    output = {"status": "ok", "runtime": "hermes-aec-runtime", "version": "0.1.0"} if args.command == "doctor" else demo()
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

