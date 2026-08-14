---
name: request-context-routing
description: Select the smallest relevant subset of an indexed AEC scene and choose the next workflow stage. Use after Scene Pre-Processing for requests to inspect, research, modify, create, verify, export, or repair model content.
---

# Request Context Routing

Call `request_context_routing` with the exact user request and current SceneIndex.

Route the result:

- Read-only inspection: return findings without creating a transaction.
- City code or product research: research first, then attach source-derived constraints.
- Geometry or metadata change: invoke `$action-assembly` with stable object IDs.
- Verification or previous failure: invoke `$proof-and-recovery`.

Ask for clarification only if multiple routed targets would materially change the outcome. Do not load unrelated project memory or enumerate every scene object.

