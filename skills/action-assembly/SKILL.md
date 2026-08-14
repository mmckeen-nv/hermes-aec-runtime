---
name: action-assembly
description: Compile a concrete AEC modification into a short, typed, reviewable AECTransaction for Rhino, Blender, FreeCAD, or a mock host. Use after targets and constraints are known and before any model mutation.
---

# Action Assembly

Call `action_assembly` with one semantic adapter operation, stable target IDs, explicit parameters, host, and the original user request.

1. Default to `dry_run=true` for a new operation or adapter.
2. Use model units from SceneIndex; never infer them from apparent dimensions.
3. Prefer one batch operation over repeated primitive calls.
4. Reject invented operation names; consult the selected adapter's operation catalog.
5. Hand the compiled transaction to `$proof-and-recovery`.

Do not produce raw clicks, keystrokes, or long command-line choreography.

