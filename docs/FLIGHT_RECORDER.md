# Flight Recorder

The Flight Recorder creates privacy-safe, append-only evidence for runtime debugging, evaluation, DML promotion, and possible future Nemotron training. It records decisions and outcomes—not chat transcripts.

Each `aec-flight-trace/1.0` envelope contains:

- the sanitized user request and request route;
- a content hash and object count for the focused scene subset, never the raw scene;
- the typed operation transaction;
- stage and tool timing;
- structured tool outcomes, execution receipt, verification, and recovery result;
- model/provider identifiers and token counts;
- a content-derived trace ID and training-quality decision.

Secrets, authorization headers, cookies, local paths, stdout/stderr, messages, transcripts, and raw request/scene/response fields are removed deterministically. Replaying identical work produces the same trace ID and is written only once.

## Recording

```python
from hermes_aec_runtime.flight_recorder import FlightRecorder, make_trace

trace = make_trace(
    request="Move the north balcony 500 mm",
    route=route.to_dict(),
    scene_subset={"objects": focused_objects},
    transaction=compiled.payload,
    timing={"elapsed_ms": 420},
    tool_outcomes=[{"tool": "rhino_apply_operations", "success": True, "duration_ms": 180}],
    receipt=receipt,
    verification=verification,
    model={"provider": "nvidia", "model": "nemotron-aec-lightning"},
    token_usage={"input_tokens": 1200, "output_tokens": 240},
)
FlightRecorder(".runtime/traces.jsonl").append(trace)
```

Writes use a single append, flush, and filesystem sync. Readers ignore an interrupted final line. The export itself is written to a temporary file, synced, and atomically replaced.

## Training-quality gate

An example is accepted only when it has a request and route, uses typed operations (never arbitrary scripts), has a completed receipt, and passes independent verification. Raw transcripts and unverified, failed, unknown, or rolled-back outcomes cannot be exported. Recovery traces may be retained and exported only after successful reconciliation and verification.

This gate is deliberately stricter than DML memory promotion. DML can keep quarantined diagnostic outcomes; the training export cannot.

## Export

From an installed development checkout:

```powershell
python tools/export_training_data.py .runtime/traces.jsonl .runtime/training.jsonl
```

The command prints accepted/rejected counts and writes deterministic `aec-tool-example/1.0` JSONL. Each line contains the sanitized request, route, hashed scene context, typed tool call, receipt, verification, model metadata, token usage, and source trace ID. This shape is suitable for conversion into a provider-specific tool-calling SFT format or direct use as an evaluation fixture.

Do not hand-edit the journal or treat it as an event bus. It is local evidence. Upload and retention policy belong to the deployment that consumes it.
