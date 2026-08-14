---
name: proof-and-recovery
description: Execute or validate an AECTransaction, inspect its ExecutionReceipt, verify the intended model delta, and recover safely from adapter failures. Use for every mutation and whenever a host call stalls, fails, or produces uncertain geometry.
---

# Proof and Recovery

Call `proof_and_recovery` exactly once for the compiled transaction and inspect the receipt.

- `validated`: dry run succeeded; request approval or execute when already authorized.
- `completed`: verify changed object IDs, counts, dimensions, and host evidence.
- `blocked`: stop and report the missing adapter or prerequisite.
- `failed`: preserve the receipt, refresh SceneIndex, and retry only with a specifically corrected transaction.

Never claim success from tool-call acceptance alone. Never recover by switching to foreground computer input. Do not repeat an identical failed transaction.

