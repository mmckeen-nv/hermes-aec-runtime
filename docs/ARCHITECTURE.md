# Architecture

Hermes remains the conversational planner. This sidecar is the execution control plane.

```text
User -> Hermes -> Scene Pre-Processing -> Context Routing -> Action Assembly
                                                        -> Proof and Recovery -> Host adapter
```

The stable boundary is three versioned values: `SceneIndex`, `AECTransaction`, and `ExecutionReceipt`. Host adapters translate those values to Rhino, Blender, or FreeCAD calls. A host adapter must expose semantic operations, validate parameters, avoid foreground input, and return evidence.

The Rhino stack now exposes a revisioned rich scene query, a validated typed-operation batch, and independent transaction verification. Arbitrary Python remains an unregistered internal escape hatch; normal Hermes profiles see only the typed surface.

## Planned adapters

- `rhino`: Rhino MCP calls and RhinoCommon scripts
- `blender`: Blender MCP calls and `bpy` operations
- `freecad`: FreeCAD MCP calls and document transactions

Fine-tuning is optional and comes later. The runtime first captures successful transactions and receipts as clean training/evaluation data for a possible **Nemotron AEC Lightning** model.
