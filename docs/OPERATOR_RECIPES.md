# Operator recipes

These recipes are short, deterministic starting points—not prompts that ask the model to invent a workflow. Canonical payloads live in [`examples/offline_recipes.json`](../examples/offline_recipes.json) and compile in CI against the same code used by the MCP tools.

## Validate everything offline

No Rhino, Blender, Hermes, API key, or network connection is required:

```powershell
python tools/run_offline_recipes.py
```

The command exits nonzero on the first invalid operation, handoff, recovery decision, memory outcome, or Flight Recorder trace.

## Rhino modifications

Use the normal sequence: call `rhino_scene_query`, resolve requested objects to stable IDs, call `rhino_apply_operations` once with the current revision and a stable idempotency key, then call `rhino_verify_transaction`.

`rhino-pool-fence-modification` shows alias chaining: create a path, extrude it, then label the result without another model turn. Its coordinates are in metres. Replace them only after checking scene units; never infer scale from visible size.

## Rhino full-build batches

`rhino-full-build-massing-batch` creates and organizes three levels in one compiled batch. Prefer coherent batches of dependent operations over one call per primitive. Keep each batch verifiable as one architectural unit—for example massing, slabs, walls, openings, then railings—instead of putting a detailed building in one undo record.

Preserve each idempotency key until its receipt is reconciled. Start the next batch only after verification succeeds.

## Blender visualization and handoff

Run `rhino-to-blender-handoff` before import. It makes units, export path, Rhino IDs, and source layers explicit. Then send `blender-cliff-house-visualization` through `blender_apply_operations` and finish with `blender_verify_transaction`.

The recipes use relative paths so they compile everywhere. At execution time, provide paths visible to the host application. Geometry remains authoritative in Rhino; Blender owns visualization, cameras, lights, rendering, and `.blend` persistence.

## Recovery

`unknown-blender-receipt-recovery` demonstrates the ambiguous case. An `unknown` mutation is reconciled by re-indexing and checking outputs. Do not submit it with a new key. A failed receipt produces a rollback plan; a completed receipt produces a verification plan. For Rhino, call `runtime_recovery_plan` and inspect the persisted receipt before retrying.

## Workflow memory

`verified-outcome-memory-promotion` passes a completed receipt, independent verification, and an allowlisted trace summary to the promotion logic. Promotion is derived, not requested by the model. Failed or unverified outcomes are rejected; marginal verified outcomes are quarantined.

In Hermes, call `workflow_memory_promote` only after verification, then `workflow_memory_list` for promoted outcomes in the same project and host.

## Flight Recorder and evaluation

`verified-flight-trace` is the smallest accepted trace. The recorder stores a scene digest and structured outcomes, never raw conversations or scenes.

```powershell
python tools/export_training_data.py .runtime/flight-recorder.jsonl .runtime/training.jsonl
python tools/evaluate_model.py --mock --training .runtime/training.jsonl --output .runtime/readiness.json
```

Exit code `2` means the readiness gate returned `NO-GO`, commonly because fewer than 200 independent examples exist. It is not an evaluator crash. Fine-tune only on `GO`, and keep held-out tasks out of training data.

## Developer rule

Add examples to `examples/offline_recipes.json`, not only prose. Extend `validate_recipe` for a new kind. `tests/test_offline_recipes.py` prevents drift across both compilers, handoff validation, recovery, memory promotion, and recorder quality gates.
