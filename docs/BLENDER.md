# Blender Control

The Blender adapter is a visualization and handoff layer, not an architectural source of truth. It accepts typed transactions for import, collection organization, transforms, materials, cameras, lights, rendering, and saving.

Reads are serialized and retried. Mutations are serialized but never blindly retried: a lost response returns `unknown`, requiring scene reconciliation with the same idempotency key. Completed receipts are replayed locally for duplicate suppression.

Rhino handoff manifests must declare source IDs, layers, source units, and the exported interchange file. Supported unit conversions are explicit; a missing unit is rejected to prevent the known meter/millimeter class of errors.

The gateway accepts a mockable `BlenderTransport`, keeping Blender and its MCP server out of contract and reliability tests. A production transport only needs to implement `call(tool, arguments)` and expose `get_scene_info` plus `execute_blender_code`.
