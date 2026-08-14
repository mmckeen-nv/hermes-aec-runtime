"""Validated semantic operations compiled for FreeCAD's document API."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any


class FreeCADOperationError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledFreeCADTransaction:
    script: str
    normalized: tuple[dict[str, Any], ...]
    fingerprint: str


_FIELDS = {
    "create_box": {"op", "id", "name", "length", "width", "height", "position"},
    "create_cylinder": {"op", "id", "name", "radius", "height", "position"},
    "transform": {"op", "target", "translation", "rotation_axis", "rotation_degrees"},
    "set_attributes": {"op", "target", "label", "group", "color", "visible"},
    "delete": {"op", "target"},
}
_MAX_OPERATIONS = 256


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FreeCADOperationError(f"{field} must be a finite number")
    result = float(value)
    if positive and result <= 0:
        raise FreeCADOperationError(f"{field} must be greater than zero")
    return result


def _vector(value: Any, field: str, default: tuple[float, float, float] | None = None) -> list[float]:
    value = default if value is None else value
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise FreeCADOperationError(f"{field} must contain three numbers")
    return [_number(item, field) for item in value]


def normalize_freecad_operations(operations: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    if not isinstance(operations, list) or not operations or len(operations) > _MAX_OPERATIONS:
        raise FreeCADOperationError("at least one operation is required")
    aliases: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict) or raw.get("op") not in _FIELDS:
            raise FreeCADOperationError(f"operations[{index}].op is unsupported")
        op = str(raw["op"])
        unknown = set(raw) - _FIELDS[op]
        if unknown:
            raise FreeCADOperationError(f"operations[{index}] has unknown fields: {', '.join(sorted(unknown))}")
        item: dict[str, Any] = {"op": op}
        if op.startswith("create_"):
            alias = raw.get("id")
            if not isinstance(alias, str) or not alias or len(alias) > 128 or alias in aliases:
                raise FreeCADOperationError(f"operations[{index}].id must be a unique alias")
            aliases.add(alias); item.update(id=alias, name=str(raw.get("name") or alias))
            item["position"] = _vector(raw.get("position"), "position", (0, 0, 0))
            for field in ({"length", "width", "height"} if op == "create_box" else {"radius", "height"}):
                item[field] = _number(raw.get(field), field, positive=True)
        else:
            target = raw.get("target")
            if not isinstance(target, str) or not target:
                raise FreeCADOperationError(f"operations[{index}].target is required")
            if target.startswith("$") and target[1:] not in aliases:
                raise FreeCADOperationError(f"operations[{index}].target references an unknown alias")
            item["target"] = target
            if op == "transform":
                item["translation"] = _vector(raw.get("translation"), "translation", (0, 0, 0))
                item["rotation_axis"] = _vector(raw.get("rotation_axis"), "rotation_axis", (0, 0, 1))
                if item["rotation_axis"] == [0.0, 0.0, 0.0]:
                    raise FreeCADOperationError("rotation_axis must be non-zero")
                item["rotation_degrees"] = _number(raw.get("rotation_degrees", 0), "rotation_degrees")
            elif op == "set_attributes":
                if "visible" in raw and not isinstance(raw["visible"], bool):
                    raise FreeCADOperationError("visible must be a boolean")
                for field in ("label", "group", "visible"):
                    if field in raw: item[field] = raw[field]
                if "color" in raw:
                    color = _vector(raw["color"], "color")
                    if any(v < 0 or v > 1 for v in color): raise FreeCADOperationError("color values must be between 0 and 1")
                    item["color"] = color
        normalized.append(item)
    return tuple(normalized)


def compile_freecad_transaction(operations: list[dict[str, Any]]) -> CompiledFreeCADTransaction:
    normalized = normalize_freecad_operations(operations)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    fingerprint = sha256(encoded.encode()).hexdigest()
    script = f'''import FreeCAD as App, json
doc = App.ActiveDocument
if doc is None: raise RuntimeError("No active FreeCAD document")
ops = json.loads({encoded!r})
aliases = {{}}
changed = []
doc.openTransaction("Hermes AEC typed transaction")
try:
    for op in ops:
        kind = op["op"]
        if kind == "create_box":
            obj = doc.addObject("Part::Box", op["name"]); obj.Length=op["length"]; obj.Width=op["width"]; obj.Height=op["height"]
            obj.Placement.Base = App.Vector(*op["position"]); aliases[op["id"]] = obj.Name
        elif kind == "create_cylinder":
            obj = doc.addObject("Part::Cylinder", op["name"]); obj.Radius=op["radius"]; obj.Height=op["height"]
            obj.Placement.Base = App.Vector(*op["position"]); aliases[op["id"]] = obj.Name
        else:
            name = aliases.get(op["target"][1:], op["target"]); obj = doc.getObject(name)
            if obj is None: raise RuntimeError("FreeCAD target not found: " + name)
            if kind == "transform":
                obj.Placement.Base = obj.Placement.Base.add(App.Vector(*op["translation"]))
                obj.Placement.Rotation = App.Rotation(App.Vector(*op["rotation_axis"]), op["rotation_degrees"]) * obj.Placement.Rotation
            elif kind == "set_attributes":
                if "label" in op: obj.Label = str(op["label"])
                if "visible" in op and hasattr(obj, "ViewObject"): obj.ViewObject.Visibility = bool(op["visible"])
                if "color" in op and hasattr(obj, "ViewObject"): obj.ViewObject.ShapeColor = tuple(op["color"])
                if "group" in op:
                    group = doc.getObject(str(op["group"])) or doc.addObject("App::DocumentObjectGroup", str(op["group"])); group.addObject(obj)
            elif kind == "delete": doc.removeObject(obj.Name)
        changed.append(op.get("id", op.get("target")))
    doc.recompute(); doc.commitTransaction()
except Exception:
    doc.abortTransaction(); raise
print("HERMES_AEC_FREECAD=" + json.dumps({{"status":"completed","fingerprint":{fingerprint!r},"changed":changed,"aliases":aliases}}, sort_keys=True))
'''
    return CompiledFreeCADTransaction(script=script, normalized=normalized, fingerprint=fingerprint)
