# Stack acceptance contract

The runtime is independently releasable. The Cliff House demo consumes a pinned release and contains no copied runtime source.

## Normal modification path

One user request should require no more than:

1. `rhino_scene_query`
2. `rhino_apply_operations`
3. `rhino_verify_transaction`

Routine operations must be typed data, not model-generated RhinoCommon. Arbitrary scripting remains an explicitly named escape hatch.

## Required runtime layers

- **Host supervision:** determine whether Rhino and MCP are ready; checkpoint successful documents; produce a recovery plan after a crash.
- **Transport gateway:** serialize calls, retry reads, reconcile uncertain mutations, persist receipts, and prevent duplicate execution.
- **Scene index:** return revisioned, filtered geometry with units, tolerance, layers, bounds, and stable IDs.
- **Operation engine:** validate and compile a batch of typed changes into one host transaction.
- **Verification:** compare requested invariants and the actual document delta.
- **Hermes workflow:** expose the smallest useful tool set and concise skills.

## Safety invariants

- Never retry an uncertain mutation with a new idempotency key.
- Never change the payload associated with an existing idempotency key.
- Never use foreground UI input for geometry construction.
- Never overwrite a protected master or hero model.
- Never claim success without a transaction receipt and independent verification.
- A failed transaction must either confirm rollback or stop with an unknown state.

## Performance targets

- Healthy bridge preflight: under 500 ms after warm-up.
- Focused scene query: under 1 second after warm-up.
- Typed transaction host time: under 2 seconds for ordinary edits.
- Normal Hermes tool loop: three calls, excluding optional research and viewport capture.
- Zero persistent geometry after every reversible benchmark.

## Demo integration seam

The demo installer supplies only:

- Runtime version and source repository.
- Host URL/port and checkpoint directory.
- Hermes MCP registration.
- Project-specific instructions and protected model paths.

The runtime must install, test, and run without the demo repository.

