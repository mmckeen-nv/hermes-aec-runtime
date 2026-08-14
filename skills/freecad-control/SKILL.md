---
name: freecad-control
description: Inspect and modify an active FreeCAD document through typed, idempotent transactions. Use on Linux/FreeCAD for boxes, cylinders, transforms, semantic attributes/groups, visibility/color changes, and deletion; use recovery guidance after an uncertain MCP response.
---

# FreeCAD Control

Prefer `aec_run_workflow` with `active_host: freecad` for the complete query, mutation, verification, memory, and trace lifecycle.

For direct control:

1. Call `freecad_scene_query`.
2. Submit one complete batch to `freecad_apply_operations` using `create_box`, `create_cylinder`, `transform`, `set_attributes`, or `delete`.
3. Give created objects short aliases and reference them later in the same batch as `$alias`.
4. Use a stable unique idempotency key.
5. Re-query and validate labels, groups, shape validity, bounds, and units.
6. Call `freecad_proof_and_recovery` when the receipt is not completed.

Do not import protected completed assets during a full build. Do not invoke Rhino on the Linux profile.
