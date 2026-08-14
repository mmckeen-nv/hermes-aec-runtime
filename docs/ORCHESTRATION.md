# Deterministic Workflow Orchestration

`WorkflowOrchestrator` connects the runtime stages without becoming another CAD
control surface:

1. `build_plan` routes the request, creates a bounded focused-query contract, and
   validates/compiles every typed operation before a host call.
2. The selected `WorkflowGateway` reads the focused pre-mutation scene.
3. Mutations require an idempotency key and execute once through the existing
   Rhino or Blender gateway. The orchestrator does not retry mutations.
4. A completed mutation triggers a fresh independent scene read and deterministic
   receipt/delta/assertion verification.
5. Every attempted mutation becomes a privacy-safe Flight Recorder trace and a
   sanitized memory outcome. Only completed, verified, high-quality outcomes are
   promoted by the memory policy.

Read-only requests stop after scene inspection and create no training or memory
record. Dry runs stop after host validation and are recorded as rejected examples,
not successful executions.

## Minimal integration

```python
from hermes_aec_runtime.orchestrator import RhinoWorkflowGateway, WorkflowOrchestrator
from hermes_aec_runtime.rhino import RhinoClient

runtime = WorkflowOrchestrator({"rhino": RhinoWorkflowGateway(RhinoClient())})
result = await runtime.run(
    request="Add a fence around the pool",
    operations=[{"op": "create_line", "start": [0, 0, 0], "end": [4, 0, 0]}],
    idempotency_key="cliff-house:pool-fence:001",
    assertions={"object_count_delta": 1},
)
```

For durable evidence, construct the orchestrator with a `FlightRecorder` and a
`FilesystemDMLAdapter`. The equivalent `BlenderWorkflowGateway` wraps the existing
typed Blender gateway.

## Safety contract

- Plans are immutable and serializable.
- Natural-language requests cannot inject host code; only typed operation
  compilers produce executable transactions.
- Host gateways retain connection, undo, idempotency, and recovery ownership.
- A timeout or failed/unknown receipt is never automatically retried.
- Verification always compares separate before/after reads.
- Rejected outcomes remain useful diagnostics but are excluded from training data.
