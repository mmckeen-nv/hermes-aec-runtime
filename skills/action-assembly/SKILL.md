---
name: action-assembly
description: Compile a concrete Rhino modification into one short batch of registered typed operations for rhino_apply_operations. Use after target IDs, document revision, dimensions, and constraints are known.
---

# Action Assembly

Call `rhino_apply_operations` once with the document revision, a stable idempotency key, the active working-document path as `checkpoint_path`, and the smallest ordered batch of registered operations.

1. Use units from `rhino_scene_query`; never infer units from apparent scale.
2. Use exact stable IDs for existing targets.
3. Prefer one batch over repeated calls.
4. Use only operations listed by the tool schema; never invent one.
5. Reuse an idempotency key only for an identical payload.
6. Hand the returned transaction receipt to `$proof-and-recovery`.

Do not generate RhinoCommon scripts, clicks, keystrokes, or command-line choreography.
