# Blender Control

The Blender adapter is a visualization and handoff layer, not an architectural source of truth. It accepts typed transactions for import, collection organization, transforms, materials, cameras, lights, rendering, and saving.

For the standard demo render, use `blender_render_archviz`: one stable call captures the largest
current 3D viewport in Blender as the render camera and owns camera setup,
managed HDRI plus sun/fill lighting, render settings, PNG creation, `.blend` persistence, and visible presentation.
This viewport behavior is the default. Use `camera_source=explicit` with both `camera_location` and
`camera_target` only when the user specifically asks for numeric camera placement.
Its `lighting_preset` is one of `daylight` (default architectural review), `golden_hour`
(warm sunset/evening requests), or `studio` (neutral material inspection). The runtime resolves only
the installer-managed, checksum-pinned library; callers never invent HDRI paths.
Call `blender_list_hdri_files` whenever the user asks what HDRIs or lighting environments are
available. It reports the managed preset name, display name, intended use, file availability, and any
additional `.hdr` or `.exr` files placed directly in the managed library.
Use `blender_apply_operations` only for custom Blender work; its MCP input is a discriminated union
that publishes every supported operation and field. Cameras accept either `target` or
`rotation_degrees`, never both.

Reads are serialized and retried. Mutations are serialized but never blindly retried: a lost response returns `unknown`, requiring scene reconciliation with the same idempotency key. Completed receipts are replayed locally for duplicate suppression.

Rhino handoff manifests must declare source IDs, layers, source units, and the exported interchange file. Supported unit conversions are explicit; a missing unit is rejected to prevent the known meter/millimeter class of errors.

The gateway accepts a mockable `BlenderTransport`, keeping Blender and its MCP server out of contract and reliability tests. A production transport only needs to implement `call(tool, arguments)` and expose `get_scene_info` plus `execute_blender_code`.
