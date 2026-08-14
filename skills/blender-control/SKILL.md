---
name: blender-control
description: Inspect, modify, and verify Blender scenes through deterministic typed transactions. Use for Blender visualization, materials, cameras, lights, rendering, or Rhino-to-Blender handoff; do not generate raw Blender Python.
---

# Blender Control

1. Call `blender_scene_query` once and retain its `document_revision`.
2. For Rhino handoffs, call `blender_validate_handoff` before importing anything.
3. Express the complete change as one `blender_apply_operations` batch with a stable unique idempotency key. Dry-run unfamiliar operation shapes first.
4. Query the scene again and inspect the intended outputs.
5. Call `blender_proof_and_recovery` with the receipt. If the status is unknown, reconcile before any retry and reuse the same key.

Never use computer control or expose generated Python when these typed tools cover the request.
