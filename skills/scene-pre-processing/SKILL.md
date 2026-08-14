---
name: scene-pre-processing
description: Query a Rhino document through the Hermes AEC sidecar and select stable object IDs before inspection or modification. Use when a model opens, changes externally, has uncertain units, or a request refers to geometry without exact IDs.
---

# Scene Pre-Processing

1. Call `rhino_health`. Stop if the sidecar or Rhino bridge is unavailable.
2. Call `rhino_scene_query` with focused filters; use an unfiltered query only for initial orientation.
3. Treat returned revision, units, IDs, layers, types, and bounds as authoritative.
4. Pass only relevant objects and the revision to `$request-context-routing`.

Refresh after an external edit, stale-revision response, or ambiguous target. Never use foreground UI input for discovery.
