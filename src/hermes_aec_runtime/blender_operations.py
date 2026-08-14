"""Typed, host-independent compiler for Blender visualization transactions."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence


class BlenderOperationError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledBlenderTransaction:
    script: str
    normalized: dict[str, Any]
    fingerprint: str


_KINDS = {
    "import_scene", "ensure_collection", "transform", "delete_objects", "assign_material",
    "create_camera", "create_light", "render_settings", "save_blend", "render",
}
_MAX_OPERATIONS = 256
_MAX_TEXT = 4_096

_FIELDS = {
    "import_scene": {"op", "id", "path", "collection"}, "ensure_collection": {"op", "id", "name"},
    "transform": {"op", "id", "objects", "location", "rotation_degrees", "scale"},
    "delete_objects": {"op", "id", "objects"},
    "assign_material": {"op", "id", "objects", "material", "base_color", "metallic", "roughness"},
    "create_camera": {"op", "id", "name", "location", "rotation_degrees", "lens_mm"},
    "create_light": {"op", "id", "name", "type", "location", "rotation_degrees", "energy"},
    "render_settings": {"op", "id", "engine", "resolution", "samples"},
    "save_blend": {"op", "id", "path"}, "render": {"op", "id", "path"},
}


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BlenderOperationError(f"{path}: must be a finite number")
    value = float(value)
    if positive and value <= 0:
        raise BlenderOperationError(f"{path}: must be greater than zero")
    return value


def _vec(value: Any, path: str, size: int = 3) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise BlenderOperationError(f"{path}: must contain {size} numbers")
    return [_number(v, f"{path}[{i}]") for i, v in enumerate(value)]


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise BlenderOperationError(f"{path}: must be a non-empty string")
    return value


def normalize_blender_operations(operations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(operations, (str, bytes)) or not isinstance(operations, Sequence) or not operations or len(operations) > _MAX_OPERATIONS:
        raise BlenderOperationError("operations: must be a non-empty array")
    result: list[dict[str, Any]] = []
    aliases: set[str] = set()
    for i, raw in enumerate(operations):
        path = f"operations[{i}]"
        if not isinstance(raw, Mapping) or raw.get("op") not in _KINDS:
            raise BlenderOperationError(f"{path}.op: unsupported operation")
        kind = str(raw["op"])
        unknown = set(raw) - _FIELDS[kind]
        if unknown:
            raise BlenderOperationError(f"{path}: unknown fields: {', '.join(sorted(unknown))}")
        alias = _text(raw.get("id", f"op_{i + 1}"), f"{path}.id")
        if alias in aliases:
            raise BlenderOperationError(f"{path}.id: must be unique")
        op: dict[str, Any] = {"op": kind, "id": alias}
        if kind == "import_scene":
            op["path"] = _text(raw.get("path"), f"{path}.path")
            ext = Path(op["path"]).suffix.lower()
            if ext not in {".fbx", ".obj", ".gltf", ".glb", ".usd", ".usda", ".usdc"}:
                raise BlenderOperationError(f"{path}.path: unsupported interchange format")
            op["collection"] = _text(raw.get("collection", "AEC Import"), f"{path}.collection")
        elif kind == "ensure_collection":
            op["name"] = _text(raw.get("name"), f"{path}.name")
        elif kind in {"transform", "delete_objects"}:
            objects = raw.get("objects", [])
            if not isinstance(objects, list): raise BlenderOperationError(f"{path}.objects: must be an array")
            op["objects"] = [_text(x, f"{path}.objects") for x in objects]
            if not op["objects"]: raise BlenderOperationError(f"{path}.objects: required")
            if kind == "delete_objects":
                result.append(op); aliases.add(alias); continue
            changed = False
            for key in ("location", "rotation_degrees", "scale"):
                if key in raw: op[key] = _vec(raw[key], f"{path}.{key}"); changed = True
            if not changed: raise BlenderOperationError(f"{path}: requires a transform")
        elif kind == "assign_material":
            objects = raw.get("objects", [])
            if not isinstance(objects, list): raise BlenderOperationError(f"{path}.objects: must be an array")
            op["objects"] = [_text(x, f"{path}.objects") for x in objects]
            if not op["objects"]: raise BlenderOperationError(f"{path}.objects: required")
            op["material"] = _text(raw.get("material"), f"{path}.material")
            op["base_color"] = _vec(raw.get("base_color", [0.8, .8, .8, 1]), f"{path}.base_color", 4)
            if any(not 0 <= x <= 1 for x in op["base_color"]): raise BlenderOperationError(f"{path}.base_color: values must be 0..1")
            op["metallic"] = _number(raw.get("metallic", 0), f"{path}.metallic")
            op["roughness"] = _number(raw.get("roughness", .5), f"{path}.roughness")
            if not 0 <= op["metallic"] <= 1 or not 0 <= op["roughness"] <= 1:
                raise BlenderOperationError(f"{path}: metallic and roughness must be 0..1")
        elif kind == "create_camera":
            op["name"] = _text(raw.get("name"), f"{path}.name"); op["location"] = _vec(raw.get("location"), f"{path}.location")
            op["rotation_degrees"] = _vec(raw.get("rotation_degrees", [0, 0, 0]), f"{path}.rotation_degrees")
            op["lens_mm"] = _number(raw.get("lens_mm", 50), f"{path}.lens_mm", positive=True)
        elif kind == "create_light":
            op["name"] = _text(raw.get("name"), f"{path}.name"); op["type"] = str(raw.get("type", "AREA")).upper()
            if op["type"] not in {"POINT", "SUN", "SPOT", "AREA"}: raise BlenderOperationError(f"{path}.type: invalid light type")
            op["location"] = _vec(raw.get("location", [0, 0, 0]), f"{path}.location")
            op["rotation_degrees"] = _vec(raw.get("rotation_degrees", [0, 0, 0]), f"{path}.rotation_degrees")
            op["energy"] = _number(raw.get("energy", 1000), f"{path}.energy", positive=True)
        elif kind == "render_settings":
            op["engine"] = str(raw.get("engine", "BLENDER_EEVEE_NEXT"))
            if op["engine"] not in {"BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH", "CYCLES"}: raise BlenderOperationError(f"{path}.engine: unsupported")
            resolution = raw.get("resolution", [1920, 1080])
            if not isinstance(resolution, (list, tuple)) or len(resolution) != 2: raise BlenderOperationError(f"{path}.resolution: requires width and height")
            op["resolution"] = [int(_number(x, f"{path}.resolution", positive=True)) for x in resolution]
            op["samples"] = int(_number(raw.get("samples", 64), f"{path}.samples", positive=True))
        elif kind in {"save_blend", "render"}:
            op["path"] = _text(raw.get("path"), f"{path}.path")
            expected = ".blend" if kind == "save_blend" else {".png", ".jpg", ".jpeg", ".exr"}
            suffix = Path(op["path"]).suffix.lower()
            if suffix != expected if isinstance(expected, str) else suffix not in expected:
                raise BlenderOperationError(f"{path}.path: invalid output extension")
        result.append(op); aliases.add(alias)
    return result


def compile_blender_transaction(operations: Sequence[Mapping[str, Any]]) -> CompiledBlenderTransaction:
    ops = normalize_blender_operations(operations)
    payload = json.dumps(ops, sort_keys=True, separators=(",", ":"))
    return CompiledBlenderTransaction(
        script=_SCRIPT.replace("__OPS__", repr(payload)),
        normalized={"schema_version": "1.0", "host": "blender", "operations": ops},
        fingerprint=sha256(payload.encode()).hexdigest(),
    )


_SCRIPT = r'''import bpy, json, math, os
ops=json.loads(__OPS__); changed=[]
def objects(names):
    missing=[n for n in names if n not in bpy.data.objects]
    if missing: raise ValueError("objects not found: "+", ".join(missing))
    return [bpy.data.objects[n] for n in names]
def collection(name):
    c=bpy.data.collections.get(name)
    if not c: c=bpy.data.collections.new(name); bpy.context.scene.collection.children.link(c)
    return c
for op in ops:
    kind=op["op"]
    if kind=="ensure_collection": collection(op["name"]); changed.append(op["name"])
    elif kind=="import_scene":
        before=set(bpy.data.objects); ext=os.path.splitext(op["path"])[1].lower()
        if ext==".fbx": bpy.ops.wm.fbx_import(filepath=op["path"])
        elif ext==".obj": bpy.ops.wm.obj_import(filepath=op["path"])
        elif ext in (".gltf",".glb"): bpy.ops.import_scene.gltf(filepath=op["path"])
        else: bpy.ops.wm.usd_import(filepath=op["path"])
        c=collection(op["collection"])
        for obj in set(bpy.data.objects)-before:
            for old in list(obj.users_collection): old.objects.unlink(obj)
            c.objects.link(obj); changed.append(obj.name)
    elif kind=="transform":
        for obj in objects(op["objects"]):
            if "location" in op: obj.location=op["location"]
            if "rotation_degrees" in op: obj.rotation_euler=[math.radians(x) for x in op["rotation_degrees"]]
            if "scale" in op: obj.scale=op["scale"]
            changed.append(obj.name)
    elif kind=="delete_objects":
        for name in op["objects"]:
            obj=bpy.data.objects.get(name)
            if obj is None: raise RuntimeError("Object not found: "+name)
            bpy.data.objects.remove(obj,do_unlink=True); changed.append(name)
    elif kind=="assign_material":
        mat=bpy.data.materials.get(op["material"]) or bpy.data.materials.new(op["material"]); mat.diffuse_color=op["base_color"]
        mat.metallic=op["metallic"]; mat.roughness=op["roughness"]
        for obj in objects(op["objects"]): obj.data.materials.clear(); obj.data.materials.append(mat); changed.append(obj.name)
    elif kind in ("create_camera","create_light"):
        data=bpy.data.cameras.new(op["name"]) if kind=="create_camera" else bpy.data.lights.new(op["name"],op["type"])
        obj=bpy.data.objects.new(op["name"],data); bpy.context.scene.collection.objects.link(obj); obj.location=op["location"]; obj.rotation_euler=[math.radians(x) for x in op["rotation_degrees"]]
        if kind=="create_camera": data.lens=op["lens_mm"]; bpy.context.scene.camera=obj
        else: data.energy=op["energy"]
        changed.append(obj.name)
    elif kind=="render_settings":
        s=bpy.context.scene; s.render.engine=op["engine"]; s.render.resolution_x,s.render.resolution_y=op["resolution"]
        if op["engine"]=="CYCLES": s.cycles.samples=op["samples"]
    elif kind=="save_blend": bpy.ops.wm.save_as_mainfile(filepath=op["path"])
    elif kind=="render": bpy.context.scene.render.filepath=op["path"]; bpy.ops.render.render(write_still=True)
print(json.dumps({"status":"completed","changed":sorted(set(changed))}))
'''
