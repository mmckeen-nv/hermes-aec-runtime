# RhinoMCP adapter map

Source reviewed: `jingcheng-chen/rhinomcp` plugin protocol and JSON contracts. The
runtime should speak the plugin's structured, length-prefixed TCP protocol rather
than call its MCP wrappers: `create_objects` and `modify_objects` return prose and
swallow exceptions, discarding IDs needed for receipts.

| Runtime operation | RhinoMCP plugin command | Contract status |
|---|---|---|
| `create_point` | `create_object`, `type=POINT` | Exact |
| `create_line` | `create_object`, `type=LINE` | Exact |
| `create_polyline` | `create_object`, `type=POLYLINE` | Exact after appending the first point when closed |
| `create_box` | `create_object`, `type=BOX` | Exact after converting min/max to size and center translation |
| `create_sphere` | `create_object`, `type=SPHERE` | Exact with center translation |
| `delete` | one `delete_object` per GUID | Exact; never use `all=true` |
| `set_attributes` | one `update_object_attributes` per GUID | Exact for name/layer/RGB/material index |
| `extrude_curve` | one `extrude_curve` per target | Exact |
| `offset_curve` | one `offset_curve` per target | Exact; runtime uses Sharp corner style |
| boolean union/intersection | matching command, `delete_sources=delete_input` | Exact |
| boolean difference | `boolean_difference` | Exact only for one base target |
| `transform_in_place` | none safely | **Blocked:** `modify_object` calls `Objects.Transform(..., true)`, which does not establish stable-GUID replacement semantics; rotation is Euler-only and its pivot differs from our arbitrary-axis contract |
| `duplicate` | none | **Blocked:** no typed duplicate command |

## Scene and receipts

1. Call `get_document_summary`.
2. Page `get_objects` at its maximum limit of 200 until `has_more=false`.
3. Normalize each object and compute its content hash; then use the common scene
   envelope. RhinoMCP exposes no document serial/revision, so the runtime revision
   remains a deterministic hash of the complete scene.
4. Send each mutation with envelope flags `include_delta=true` and
   `include_health=true`. `_delta` supplies created/deleted counts and small ID
   arrays; `_health` is useful evidence but does not replace the independent full
   post-query.
5. Construct the receipt from before/after scene indexes. RhinoMCP has no
   idempotency key, durable transaction journal, or atomic multi-command batch.
   The runtime must retain its mutation lock, unknown-outcome reconciliation,
   verification, and receipt store.

## Required pilot guardrails

- Loopback only (`127.0.0.1:1999`) and strict schema validation.
- Disable `run_command`, RhinoScript Python, and RhinoCommon C# in ordinary profiles.
- Do not retry a mutation after timeout or disconnect; mark it `unknown` and
  reconcile by re-indexing.
- Execute aliases sequentially from structured result fields (`id`, `result_id`,
  or `result_ids`); never infer IDs from names.
- Roll back a partially completed multi-command transaction using the Rhino undo
  record exposed per plugin command only after reconciling actual state. RhinoMCP
  does not provide one undo record spanning the full runtime transaction.
- Keep the existing bridge for `transform_in_place` and `duplicate` until the
  plugin gains stable-ID transforms and typed duplication, or contribute those
  two operations upstream.

The offline compiler is in `rhinomcp_mapping.py`; it fails closed for the two
unsupported runtime operations.
