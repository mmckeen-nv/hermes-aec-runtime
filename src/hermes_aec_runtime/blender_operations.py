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
    "create_camera", "create_light", "set_world_hdri", "render_settings", "save_blend", "render", "present_scene",
}
_MAX_OPERATIONS = 256
_MAX_TEXT = 4_096

_FIELDS = {
    "import_scene": {"op", "id", "path", "collection", "source_host", "unit_scale", "unit_scale_to_meters"}, "ensure_collection": {"op", "id", "name"},
    "transform": {"op", "id", "objects", "location", "rotation_degrees", "scale"},
    "delete_objects": {"op", "id", "objects"},
    "assign_material": {"op", "id", "objects", "material", "base_color", "metallic", "roughness"},
    "create_camera": {"op", "id", "name", "location", "target", "rotation_degrees", "lens_mm"},
    "create_light": {"op", "id", "name", "type", "location", "rotation_degrees", "energy"},
    "set_world_hdri": {"op", "id", "path", "strength", "rotation_degrees"},
    "render_settings": {"op", "id", "engine", "resolution", "samples"},
    "save_blend": {"op", "id", "path"}, "render": {"op", "id", "path"},
    "present_scene": {"op", "id"},
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
            op["source_host"] = str(raw.get("source_host", "rhino")).lower()
            if op["source_host"] != "rhino":
                raise BlenderOperationError(f"{path}.source_host: must be rhino")
            if "unit_scale" in raw and "unit_scale_to_meters" in raw:
                raise BlenderOperationError(f"{path}: specify only one unit scale field")
            scale_value = raw.get("unit_scale", raw.get("unit_scale_to_meters", 1.0))
            op["unit_scale"] = _number(scale_value, f"{path}.unit_scale", positive=True)
            if not 1e-9 <= op["unit_scale"] <= 1e9:
                raise BlenderOperationError(f"{path}.unit_scale: outside supported range")
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
            if "target" in raw and "rotation_degrees" in raw:
                raise BlenderOperationError(f"{path}: specify target or rotation_degrees, not both")
            if "target" in raw: op["target"] = _vec(raw["target"], f"{path}.target")
            else: op["rotation_degrees"] = _vec(raw.get("rotation_degrees", [0, 0, 0]), f"{path}.rotation_degrees")
            op["lens_mm"] = _number(raw.get("lens_mm", 50), f"{path}.lens_mm", positive=True)
        elif kind == "create_light":
            op["name"] = _text(raw.get("name"), f"{path}.name"); op["type"] = str(raw.get("type", "AREA")).upper()
            if op["type"] not in {"POINT", "SUN", "SPOT", "AREA"}: raise BlenderOperationError(f"{path}.type: invalid light type")
            op["location"] = _vec(raw.get("location", [0, 0, 0]), f"{path}.location")
            op["rotation_degrees"] = _vec(raw.get("rotation_degrees", [0, 0, 0]), f"{path}.rotation_degrees")
            op["energy"] = _number(raw.get("energy", 1000), f"{path}.energy", positive=True)
        elif kind == "set_world_hdri":
            op["path"] = _text(raw.get("path"), f"{path}.path")
            if Path(op["path"]).suffix.lower() not in {".hdr", ".exr"}:
                raise BlenderOperationError(f"{path}.path: must be an .hdr or .exr image")
            op["strength"] = _number(raw.get("strength", 1.0), f"{path}.strength", positive=True)
            if op["strength"] > 10:
                raise BlenderOperationError(f"{path}.strength: must be no greater than 10")
            op["rotation_degrees"] = _number(raw.get("rotation_degrees", 0.0), f"{path}.rotation_degrees")
        elif kind == "render_settings":
            op["engine"] = str(raw.get("engine", "BLENDER_EEVEE_NEXT"))
            if op["engine"] not in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH", "CYCLES"}: raise BlenderOperationError(f"{path}.engine: unsupported")
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
        elif kind == "present_scene":
            pass
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
from mathutils import Vector
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
            c.objects.link(obj)
            if op["unit_scale"] != 1.0: obj.scale=[component*op["unit_scale"] for component in obj.scale]
            changed.append(obj.name)
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
        obj=bpy.data.objects.new(op["name"],data); bpy.context.scene.collection.objects.link(obj); obj.location=op["location"]
        if kind=="create_camera" and "target" in op:
            direction=Vector(op["target"])-obj.location
            if direction.length < 1e-9: raise ValueError("camera target must differ from location")
            obj.rotation_euler=direction.to_track_quat("-Z","Y").to_euler()
        else: obj.rotation_euler=[math.radians(x) for x in op["rotation_degrees"]]
        if kind=="create_camera": data.lens=op["lens_mm"]; bpy.context.scene.camera=obj
        else: data.energy=op["energy"]
        changed.append(obj.name)
    elif kind=="set_world_hdri":
        if not os.path.isfile(op["path"]): raise ValueError("HDRI file not found: "+op["path"])
        world=bpy.context.scene.world or bpy.data.worlds.new("AEC HDRI World")
        bpy.context.scene.world=world; world.use_nodes=True
        nodes=world.node_tree.nodes; links=world.node_tree.links; nodes.clear()
        tex=nodes.new("ShaderNodeTexCoord"); mapping=nodes.new("ShaderNodeMapping")
        environment=nodes.new("ShaderNodeTexEnvironment"); background=nodes.new("ShaderNodeBackground")
        output=nodes.new("ShaderNodeOutputWorld")
        environment.image=bpy.data.images.load(op["path"],check_existing=True)
        mapping.inputs["Rotation"].default_value[2]=math.radians(op["rotation_degrees"])
        background.inputs["Strength"].default_value=op["strength"]
        links.new(tex.outputs["Generated"],mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"],environment.inputs["Vector"])
        links.new(environment.outputs["Color"],background.inputs["Color"])
        links.new(background.outputs["Background"],output.inputs["Surface"])
        changed.append("__world_hdri__")
    elif kind=="render_settings":
        s=bpy.context.scene; requested=op["engine"]
        try: s.render.engine=requested
        except TypeError:
            fallback={"BLENDER_EEVEE_NEXT":"BLENDER_EEVEE","BLENDER_EEVEE":"BLENDER_EEVEE_NEXT"}.get(requested)
            if not fallback: raise
            requested=fallback; s.render.engine=requested
        s.render.resolution_x,s.render.resolution_y=op["resolution"]
        if requested=="CYCLES": s.cycles.samples=op["samples"]
    elif kind=="save_blend": bpy.ops.wm.save_as_mainfile(filepath=op["path"])
    elif kind=="render": bpy.context.scene.render.filepath=op["path"]; bpy.ops.render.render(write_still=True)
    elif kind=="present_scene":
        from mathutils import Vector
        visible=[obj for obj in bpy.context.scene.objects if obj.type=="MESH" and not obj.hide_viewport]
        corners=[obj.matrix_world @ Vector(corner) for obj in visible for corner in obj.bound_box]
        if corners:
            low=Vector((min(p.x for p in corners),min(p.y for p in corners),min(p.z for p in corners)))
            high=Vector((max(p.x for p in corners),max(p.y for p in corners),max(p.z for p in corners)))
            center=(low+high)*0.5; distance=max(high-low)*0.75
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type=="VIEW_3D": area.spaces.active.region_3d.view_location=center; area.spaces.active.region_3d.view_distance=max(distance,1.0)
        if os.name=="nt":
            import ctypes
            pid=os.getpid(); handles=[]
            callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
            def owned(hwnd,_):
                found=ctypes.c_ulong(); ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(found))
                if found.value==pid and ctypes.windll.user32.IsWindowVisible(hwnd): handles.append(hwnd)
                return True
            ctypes.windll.user32.EnumWindows(callback(owned),0)
            for hwnd in handles: ctypes.windll.user32.ShowWindow(hwnd,9); ctypes.windll.user32.BringWindowToTop(hwnd); ctypes.windll.user32.SetForegroundWindow(hwnd)
        changed.append("__presented_scene__")
print(json.dumps({"status":"completed","changed":sorted(set(changed))}))
'''
