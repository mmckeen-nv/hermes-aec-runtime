---
name: request-context-routing
description: Route an AEC request using the smallest useful subset returned by rhino_scene_query. Use after Scene Pre-Processing for requests to inspect, research, create, modify, verify, export, or repair Rhino content.
---

# Request Context Routing

Route the exact request:

- Read-only inspection: return findings without creating a transaction.
- City code or product research: research first, then attach source-derived constraints.
- Geometry or metadata change: invoke `$action-assembly` with stable IDs and document revision.
- Verification or previous failure: invoke `$proof-and-recovery`.

Ask only when ambiguous targets would materially change the outcome. Refine with `rhino_scene_query`; do not enumerate the entire document repeatedly.
