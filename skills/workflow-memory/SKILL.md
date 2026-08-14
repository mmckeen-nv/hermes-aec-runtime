---
name: workflow-memory
description: Promote successful typed AEC executions into sanitized project-scoped workflow memory. Use only after independent verification; use querying to reuse proven operation patterns without replaying raw conversations.
---

# Workflow Memory

1. Promote only a completed receipt with an independent `verified` result.
2. Call `workflow_memory_promote` with project, host, operation signature, receipt, verification, and compact trace events.
3. Treat `quarantined` and `rejected` results as non-reusable.
4. Call `workflow_memory_query` for `promoted` outcomes when a similar typed operation is requested.

Memory is advisory. Always refresh the scene, validate target IDs, and execute through the normal transaction and proof workflow.
