# Workflow Memory

Workflow Memory stores compact, verified execution outcomes—not conversations. `create_outcome` accepts an execution receipt, independent verification result, an allowlisted trace summary, and an operation signature. Prompt text, messages, transcripts, console streams, credentials, and local paths are discarded or redacted before persistence.

Outcomes are scoped by project and host, deterministically deduplicated, and assigned one of three states:

- **promoted**: completed, independently verified, and above the promotion threshold.
- **quarantined**: valid but below the promotion threshold; retain for review, never inject automatically.
- **rejected**: failed, unverified, or below the minimum quality threshold.

`DMLAdapter` is the integration boundary for the production DML harness. `MemoryDMLAdapter` is an offline test implementation. `FilesystemDMLAdapter` is the local reference implementation and writes only sanitized outcome JSON. A remote DML adapter should preserve the same project/host isolation and idempotent `outcome_id` behavior.
