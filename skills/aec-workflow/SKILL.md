---
name: aec-workflow
description: Execute or inspect an AEC request through one deterministic route, focused scene query, typed transaction, independent verification, workflow-memory outcome, and Flight Recorder trace. Use for routine Rhino, FreeCAD, or Blender work when typed operations cover the request.
---

# AEC Workflow

1. Translate the requested change into the smallest complete typed operation batch.
2. Call `aec_workflow_plan` when target, host, risk, or operation validity is uncertain.
3. Call `aec_run_workflow` with the exact request, active host, operations, project ID, and a stable unique idempotency key.
4. Report success only when the returned status is `verified`.
5. If status is `unknown`, stop and follow the returned recovery guidance. Never create a new key for the same attempt.

For read-only inspection, omit operations and the idempotency key. Use web research separately when the route says `needs_web`; pass researched constraints into the typed operation parameters.

Do not use foreground computer control. Use host-specific escape tools only when no typed operation exists and the active profile explicitly exposes one.
