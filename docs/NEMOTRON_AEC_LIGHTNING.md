# Nemotron AEC Lightning readiness

Nemotron AEC Lightning is a proposed model name, not an existing fine-tune. This phase decides whether a model and dataset are ready for fine-tuning. It is deliberately provider-neutral and never executes geometry.

## Evaluation boundary

Providers convert a model response into this normalized candidate shape:

```json
{
  "route": {"kind": "modify", "host": "rhino"},
  "tools": ["transform_in_place"],
  "transaction": {
    "schema_version": "1.0.0",
    "kind": "operation_transaction",
    "id": "tx-1",
    "created_at": 0,
    "host": "rhino",
    "document_revision": 42,
    "idempotency_key": "request-42-move-wall",
    "operations": [{"op": "transform_in_place"}]
  },
  "verification": {"required": true},
  "usage": {
    "tool_calls": 3,
    "elapsed_ms": 900,
    "input_tokens": 1200,
    "output_tokens": 240,
    "operations": 1,
    "script_bytes": 0
  }
}
```

Candidate records supplied to the CLI use `{"task_id":"...","candidate":{...}}`. JSON and JSONL are supported. Flight Recorder training examples may also be JSON or JSONL. No provider credentials are needed by the evaluator.

## Scores and gates

The score covers routing, Runtime Contract transaction validity, typed tool choice, safety/idempotency, verification discipline, latency/token budget compliance, and Rhino-versus-Blender selection. Transaction validity, safety, verification, and host selection are release-critical.

Default fine-tuning readiness requires:

- Overall score at least 0.90.
- Critical metric scores at least 0.95.
- Host selection at least 0.95.
- At least 20 held-out evaluation tasks.
- At least 200 promoted training examples.
- At most 5% exact semantic duplicates.
- No prompt overlap with the held-out evaluation set.
- No detected API credentials.

The dataset gate is independent of model quality. A perfect offline reference run remains **NO-GO** when no clean training dataset is supplied. This prevents a mock or a small hand-authored suite from being mistaken for fine-tuning readiness.

## Run offline

```powershell
python tools/evaluate_model.py --mock --output .runtime/nemotron-readiness.json
```

The offline mock validates the harness and reference expectations. It normally exits `2` because the repository does not ship a training dataset. A real model evaluation uses normalized outputs:

```powershell
python tools/evaluate_model.py `
  --candidates .runtime/candidate-outputs.jsonl `
  --training .runtime/promoted-flight-recorder-examples.jsonl `
  --provider nvidia `
  --model nemotron-lightning `
  --output .runtime/nemotron-readiness.json
```

Exit `0` means all readiness gates passed; exit `2` means NO-GO. Malformed input or CLI misuse is an error. The resulting JSON contains task-level failures, aggregate metrics, dataset audit findings, blockers, and the explicit `fine_tune_ready` decision.

## Data handling

Only promoted, verified Flight Recorder examples belong in the training input. Keep the held-out prompts separate before collection starts. The evaluator fingerprints semantic fields, detects exact duplicates, checks prompt overlap, and scans for common credential patterns. These checks are minimum safeguards, not a substitute for a human privacy and licensing review.

Fine-tuning should begin only after a real candidate model passes the runtime gates and the dataset audit returns `GO`. Until then, use the base model with the deterministic AEC runtime.
