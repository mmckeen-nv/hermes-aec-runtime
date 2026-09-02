---
name: blender-control
description: Inspect, modify, and verify Blender scenes through deterministic typed transactions. Use for Blender visualization, materials, cameras, lights, rendering, or Rhino-to-Blender handoff; do not generate raw Blender Python.
---

# Blender Control

1. Call `blender_scene_query` once and retain its `document_revision`.
2. For Rhino handoffs, call `rhino_export_scene` once with a new absolute `.glb` path under the active workspace and `expected_units: Meters`; GLB uses Rhino's dedicated deterministic glTF writer. Retain its completed export receipt. Never ask the operator to export manually and never pass `.3dm` directly to Blender.
3. Call `blender_validate_handoff` with that receipt and the source IDs/layers before importing anything.
4. Express the complete change as one `blender_apply_operations` batch with a stable unique idempotency key. Dry-run unfamiliar operation shapes first.
5. Query the scene again and inspect the intended outputs.
6. Call `blender_proof_and_recovery` with the receipt. If the status is unknown, reconcile before any retry and reuse the same key.

For a standard render, call `blender_render_archviz` and choose exactly one managed `lighting_preset`:
`daylight` by default, `golden_hour` for sunset/evening/warm requests, or `studio` for neutral
material inspection. Never invent an HDRI path or use a loose downloaded environment file.

When the user asks which HDRIs, environments, or lighting presets are available, call
`blender_list_hdri_files` and report its friendly names, purposes, and availability. Do not infer the
installed library from memory or enumerate unrelated filesystem locations.

Never use computer control or expose generated Python when these typed tools cover the request.
