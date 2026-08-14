---
name: proof-and-recovery
description: Verify a typed Rhino transaction through rhino_verify_transaction and recover without duplicating geometry. Use after every rhino_apply_operations call and whenever a Rhino operation stalls, fails, or has an uncertain outcome.
---

# Proof and Recovery

Call `rhino_verify_transaction` with the returned transaction ID and explicit assertions. Never claim success from tool acceptance or a completed status alone.

If status is `unknown`, retry the identical `rhino_apply_operations` payload with the same idempotency key. If `rolled_back=true`, correct the operation batch and use a new key. Never change a payload while retaining its key.

- `completed` and assertions pass: report the verified model delta.
- `unknown`: reconcile with the same key; do not submit new geometry.
- `stale`: refresh with `rhino_scene_query`, then re-plan.
- `failed` with rollback: preserve evidence and submit only a corrected batch.
- failed verification: stop or correct the specific discrepancy.

Never recover through foreground computer input.
