# Architecture

Hermes remains the conversational planner. This sidecar is the execution control plane.

```text
User -> Hermes -> Scene Pre-Processing -> Context Routing -> Action Assembly
                                                        -> Proof and Recovery -> Host adapter
```

The stable boundary is three versioned values: `SceneIndex`, `AECTransaction`, and `ExecutionReceipt`. Host adapters translate those values to Rhino, Blender, or FreeCAD calls. A host adapter must expose semantic operations, validate parameters, avoid foreground input, and return evidence.

The Rhino stack now exposes a revisioned rich scene query, a validated typed-operation batch, and independent transaction verification. Arbitrary Python remains an unregistered internal escape hatch; normal Hermes profiles see only the typed surface.

## Host adapters

- `rhino`: revisioned scene audit and transactional RhinoCommon compiler
- `blender`: scene audit, typed `bpy` transactions, and handoff validation
- `freecad`: scene audit and native FreeCAD document transactions for the first deterministic operation set

`aec_run_workflow` composes these adapters behind a single fast path. It never bypasses host transaction, idempotency, proof, memory, or trace boundaries.

Fine-tuning is optional and comes later. The runtime first captures successful transactions and receipts as clean training/evaluation data for a possible **Nemotron AEC Lightning** model.
