---
name: scene-pre-processing
description: Build or refresh a compact SceneIndex before reasoning about an unfamiliar Rhino, Blender, or FreeCAD document. Use when a model is opened, changed outside Hermes, units or object identity are uncertain, or a request refers to visible geometry without stable IDs.
---

# Scene Pre-Processing

Call `scene_preprocessing` once for the active document snapshot. Treat its returned object IDs, units, layers, types, and bounds as authoritative for the turn.

1. Reuse a current index when the document revision is unchanged.
2. Refresh after any external edit or ambiguous target error.
3. Report a unit mismatch before compiling dimensions.
4. Pass the index to `$request-context-routing`; do not dump the full document into subsequent prompts.

Never mutate geometry during this stage and never use foreground UI input to discover the scene.

