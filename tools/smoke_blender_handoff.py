"""Headless, disposable smoke test for the typed Rhino-to-Blender import operation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hermes_aec_runtime.blender_operations import compile_blender_transaction  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hermes-aec-blender-smoke-") as temporary:
        handoff = Path(temporary) / "handoff.glb"
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        bpy.context.object.name = "HandoffCube"
        bpy.ops.export_scene.gltf(filepath=str(handoff), export_format="GLB", use_selection=False)
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

        compiled = compile_blender_transaction([{
            "op": "import_scene",
            "path": str(handoff),
            "collection": "Rhino Handoff",
            "source_host": "rhino",
            "unit_scale": 0.5,
        }])
        exec(compile(compiled.script, "<hermes-aec-transaction>", "exec"), {})

        imported = bpy.data.objects.get("HandoffCube")
        assert imported is not None, "GLB object was not imported"
        assert imported.name in bpy.data.collections["Rhino Handoff"].objects, "object was not placed in handoff collection"
        assert tuple(round(value, 6) for value in imported.scale) == (0.5, 0.5, 0.5), "unit scale was not applied"
        print("BLENDER_HANDOFF_SMOKE_PASS source_host=rhino unit_scale=0.5")


if __name__ == "__main__":
    main()
