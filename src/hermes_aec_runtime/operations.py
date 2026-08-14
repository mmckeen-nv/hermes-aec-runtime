"""Typed, deterministic Rhino operation compiler.

This module deliberately has no Rhino dependency.  It validates an operation batch
and emits one self-contained script for execution by the existing Rhino bridge.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence
from uuid import UUID


class OperationValidationError(ValueError):
    """A typed operation batch is invalid and must not be sent to Rhino."""


@dataclass(frozen=True)
class CompiledTransaction:
    script: str
    normalized: dict[str, Any]
    fingerprint: str
    expected_change: str


_KINDS = {
    "create_point", "create_line", "create_polyline", "create_box", "create_sphere",
    "transform_in_place", "duplicate", "delete", "set_attributes", "extrude_curve",
    "offset_curve", "boolean_union", "boolean_difference", "boolean_intersection",
}
_MAX_OPERATIONS = 256
_MAX_POINTS = 10_000
_MAX_TEXT = 4_096


def _fail(path: str, message: str) -> None:
    raise OperationValidationError(f"{path}: {message}")


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(path, "must be a finite number")
    result = float(value)
    if positive and result <= 0:
        _fail(path, "must be greater than zero")
    return result


def _vector(value: Any, path: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        _fail(path, "must be a three-number array")
    return [_number(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _targets(value: Any, path: str, known_aliases: set[str]) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > _MAX_OPERATIONS:
        _fail(path, "must be a non-empty array")
    result: list[str] = []
    for index, target in enumerate(value):
        if not isinstance(target, str) or not target.strip() or len(target) > _MAX_TEXT:
            _fail(f"{path}[{index}]", "must be a GUID or $operation_id reference")
        if target.startswith("$") and target[1:] not in known_aliases:
            _fail(f"{path}[{index}]", f"references unknown or future operation {target!r}")
        if not target.startswith("$"):
            try:
                UUID(target)
            except (ValueError, AttributeError):
                _fail(f"{path}[{index}]", "must be a valid GUID or $operation_id reference")
        result.append(target)
    return result


def _keys(op: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(op) - allowed - {"op", "id"})
    if unknown:
        _fail(path, f"unknown fields: {', '.join(unknown)}")


def normalize_operations(operations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate operations and return a canonical JSON-compatible representation."""
    if isinstance(operations, (str, bytes)) or not isinstance(operations, Sequence) or not operations or len(operations) > _MAX_OPERATIONS:
        _fail("operations", "must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    aliases: set[str] = set()
    for index, raw in enumerate(operations):
        path = f"operations[{index}]"
        if not isinstance(raw, Mapping):
            _fail(path, "must be an object")
        kind = raw.get("op")
        if kind not in _KINDS:
            _fail(f"{path}.op", f"must be one of {', '.join(sorted(_KINDS))}")
        alias = raw.get("id", f"op_{index + 1}")
        if not isinstance(alias, str) or not alias or len(alias) > 128 or not alias.replace("_", "a").replace("-", "a").isalnum():
            _fail(f"{path}.id", "must contain only letters, numbers, underscores, or hyphens")
        if alias in aliases:
            _fail(f"{path}.id", "must be unique")
        out: dict[str, Any] = {"op": kind, "id": alias}
        if kind == "create_point":
            _keys(raw, {"point"}, path); out["point"] = _vector(raw.get("point"), f"{path}.point")
        elif kind == "create_line":
            _keys(raw, {"start", "end"}, path)
            out["start"] = _vector(raw.get("start"), f"{path}.start"); out["end"] = _vector(raw.get("end"), f"{path}.end")
            if out["start"] == out["end"]: _fail(path, "line endpoints must differ")
        elif kind == "create_polyline":
            _keys(raw, {"points", "closed"}, path)
            points = raw.get("points")
            if not isinstance(points, list) or len(points) < 2 or len(points) > _MAX_POINTS: _fail(f"{path}.points", "must contain between two and 10000 points")
            out["points"] = [_vector(p, f"{path}.points[{i}]") for i, p in enumerate(points)]
            if not isinstance(raw.get("closed", False), bool): _fail(f"{path}.closed", "must be a boolean")
            out["closed"] = raw.get("closed", False)
            if out["closed"] and len(points) < 3: _fail(f"{path}.points", "closed polyline requires at least three points")
        elif kind == "create_box":
            _keys(raw, {"min", "max"}, path)
            out["min"] = _vector(raw.get("min"), f"{path}.min"); out["max"] = _vector(raw.get("max"), f"{path}.max")
            if any(a >= b for a, b in zip(out["min"], out["max"])): _fail(path, "box max must exceed min on every axis")
        elif kind == "create_sphere":
            _keys(raw, {"center", "radius"}, path)
            out["center"] = _vector(raw.get("center"), f"{path}.center"); out["radius"] = _number(raw.get("radius"), f"{path}.radius", positive=True)
        elif kind == "transform_in_place":
            _keys(raw, {"targets", "translation", "rotation", "scale", "center"}, path)
            out["targets"] = _targets(raw.get("targets"), f"{path}.targets", aliases)
            present = [k for k in ("translation", "rotation", "scale") if k in raw]
            if len(present) != 1: _fail(path, "specify exactly one of translation, rotation, or scale")
            if "translation" in raw: out["translation"] = _vector(raw["translation"], f"{path}.translation")
            if "rotation" in raw:
                rotation = raw["rotation"]
                if not isinstance(rotation, Mapping): _fail(f"{path}.rotation", "must be an object")
                if set(rotation) != {"axis", "degrees"}: _fail(f"{path}.rotation", "requires only axis and degrees")
                out["rotation"] = {"axis": _vector(rotation["axis"], f"{path}.rotation.axis"), "degrees": _number(rotation["degrees"], f"{path}.rotation.degrees")}
                if out["rotation"]["axis"] == [0.0, 0.0, 0.0]: _fail(f"{path}.rotation.axis", "must be non-zero")
            if "scale" in raw: out["scale"] = _number(raw["scale"], f"{path}.scale", positive=True)
            if "center" in raw: out["center"] = _vector(raw["center"], f"{path}.center")
        elif kind in {"duplicate", "delete"}:
            _keys(raw, {"targets", "translation"}, path)
            out["targets"] = _targets(raw.get("targets"), f"{path}.targets", aliases)
            if "translation" in raw:
                if kind == "delete": _fail(path, "delete does not accept translation")
                out["translation"] = _vector(raw["translation"], f"{path}.translation")
        elif kind == "set_attributes":
            _keys(raw, {"targets", "name", "layer", "color", "material_index"}, path)
            out["targets"] = _targets(raw.get("targets"), f"{path}.targets", aliases)
            for field in ("name", "layer"):
                if field in raw:
                    if not isinstance(raw[field], str) or not raw[field].strip() or len(raw[field]) > _MAX_TEXT: _fail(f"{path}.{field}", "must be a non-empty bounded string")
                    out[field] = raw[field]
            if "color" in raw:
                color = raw["color"]
                if not isinstance(color, list) or len(color) not in (3, 4) or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in color):
                    _fail(f"{path}.color", "must be [r,g,b] or [r,g,b,a] integers from 0 to 255")
                out["color"] = color
            if "material_index" in raw:
                if isinstance(raw["material_index"], bool) or not isinstance(raw["material_index"], int) or raw["material_index"] < -1: _fail(f"{path}.material_index", "must be an integer >= -1")
                out["material_index"] = raw["material_index"]
            if len(out) == 3: _fail(path, "requires at least one attribute change")
        elif kind in {"extrude_curve", "offset_curve"}:
            allowed = {"targets", "vector", "cap"} if kind == "extrude_curve" else {"targets", "distance", "normal"}
            _keys(raw, allowed, path); out["targets"] = _targets(raw.get("targets"), f"{path}.targets", aliases)
            if kind == "extrude_curve":
                if not isinstance(raw.get("cap", True), bool): _fail(f"{path}.cap", "must be a boolean")
                out["vector"] = _vector(raw.get("vector"), f"{path}.vector"); out["cap"] = raw.get("cap", True)
                if out["vector"] == [0.0, 0.0, 0.0]: _fail(f"{path}.vector", "must be non-zero")
            else:
                out["distance"] = _number(raw.get("distance"), f"{path}.distance")
                if out["distance"] == 0: _fail(f"{path}.distance", "must be non-zero")
                out["normal"] = _vector(raw.get("normal", [0, 0, 1]), f"{path}.normal")
        else:
            _keys(raw, {"targets", "cutters", "delete_input"}, path)
            out["targets"] = _targets(raw.get("targets"), f"{path}.targets", aliases)
            if kind == "boolean_difference": out["cutters"] = _targets(raw.get("cutters"), f"{path}.cutters", aliases)
            elif "cutters" in raw: _fail(path, f"{kind} does not accept cutters")
            if not isinstance(raw.get("delete_input", True), bool): _fail(f"{path}.delete_input", "must be a boolean")
            out["delete_input"] = raw.get("delete_input", True)
        normalized.append(out); aliases.add(alias)
    return normalized


def compile_transaction(operations: Sequence[Mapping[str, Any]]) -> CompiledTransaction:
    """Compile a validated batch into one atomic-ish Rhino Python script.

    The existing sidecar owns the undo record and rollback. This script guarantees
    in-place transforms by replacing geometry under the same GUID, stable alias resolution, and a structured
    final stdout receipt.
    """
    ops = normalize_operations(operations)
    payload = json.dumps(ops, sort_keys=True, separators=(",", ":"))
    fingerprint = sha256(payload.encode("utf-8")).hexdigest()
    script = _SCRIPT.replace("__OPERATIONS_JSON__", repr(payload))
    kinds = ", ".join(op["op"] for op in ops)
    return CompiledTransaction(script, {"schema_version": "1.0", "operations": ops}, fingerprint, f"typed batch: {kinds}")


_SCRIPT = r'''import json
import Rhino
import System
from System.Drawing import Color

doc = __rhino_doc__
ops = json.loads(__OPERATIONS_JSON__)
aliases = {}
created, modified, deleted = [], [], []

def point(v): return Rhino.Geometry.Point3d(v[0], v[1], v[2])
def vector(v): return Rhino.Geometry.Vector3d(v[0], v[1], v[2])
def ids(values):
    answer = []
    for value in values:
        if value.startswith("$"):
            answer.extend(aliases[value[1:]])
        else:
            parsed = System.Guid.Parse(value)
            if doc.Objects.FindId(parsed) is None: raise ValueError("object not found: " + value)
            answer.append(parsed)
    return answer
def add(geometry, attributes=None):
    object_id = doc.Objects.Add(geometry, attributes) if attributes else doc.Objects.Add(geometry)
    if object_id == System.Guid.Empty: raise RuntimeError("Rhino failed to add geometry")
    created.append(str(object_id)); return object_id

for op in ops:
    kind, output = op["op"], []
    if kind == "create_point": output = [add(Rhino.Geometry.Point(point(op["point"])))]
    elif kind == "create_line": output = [add(Rhino.Geometry.LineCurve(point(op["start"]), point(op["end"])))]
    elif kind == "create_polyline":
        pts = [point(v) for v in op["points"]]
        if op["closed"] and pts[0] != pts[-1]: pts.append(pts[0])
        output = [add(Rhino.Geometry.PolylineCurve(pts))]
    elif kind == "create_box":
        box = Rhino.Geometry.Box(Rhino.Geometry.BoundingBox(point(op["min"]), point(op["max"])))
        output = [add(box.ToBrep())]
    elif kind == "create_sphere": output = [add(Rhino.Geometry.Sphere(point(op["center"]), op["radius"]).ToBrep())]
    elif kind == "transform_in_place":
        center = point(op.get("center", [0, 0, 0]))
        if "translation" in op: xform = Rhino.Geometry.Transform.Translation(vector(op["translation"]))
        elif "rotation" in op: xform = Rhino.Geometry.Transform.Rotation(Rhino.RhinoMath.ToRadians(op["rotation"]["degrees"]), vector(op["rotation"]["axis"]), center)
        else: xform = Rhino.Geometry.Transform.Scale(center, op["scale"])
        for object_id in ids(op["targets"]):
            source = doc.Objects.FindId(object_id)
            geometry = source.Geometry.Duplicate()
            if not geometry.Transform(xform): raise RuntimeError("geometry transform failed: " + str(object_id))
            if not doc.Objects.Replace(object_id, geometry): raise RuntimeError("in-place replacement failed: " + str(object_id))
            modified.append(str(object_id)); output.append(object_id)
    elif kind == "duplicate":
        xform = Rhino.Geometry.Transform.Translation(vector(op.get("translation", [0, 0, 0])))
        for object_id in ids(op["targets"]):
            source = doc.Objects.FindId(object_id)
            geometry, attributes = source.Geometry.Duplicate(), source.Attributes.Duplicate()
            geometry.Transform(xform); output.append(add(geometry, attributes))
    elif kind == "delete":
        for object_id in ids(op["targets"]):
            if not doc.Objects.Delete(object_id, True): raise RuntimeError("delete failed: " + str(object_id))
            deleted.append(str(object_id)); output.append(object_id)
    elif kind == "set_attributes":
        for object_id in ids(op["targets"]):
            obj = doc.Objects.FindId(object_id); attrs = obj.Attributes.Duplicate()
            if "name" in op: attrs.Name = op["name"]
            if "layer" in op:
                layer_index = doc.Layers.FindByFullPath(op["layer"], -1)
                if layer_index < 0: layer_index = doc.Layers.Add(op["layer"], Color.Black)
                attrs.LayerIndex = layer_index
            if "color" in op:
                rgba = op["color"]
                attrs.ObjectColor = Color.FromArgb(rgba[3], rgba[0], rgba[1], rgba[2]) if len(rgba) == 4 else Color.FromArgb(*rgba)
                attrs.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
            if "material_index" in op: attrs.MaterialIndex = op["material_index"]; attrs.MaterialSource = Rhino.DocObjects.ObjectMaterialSource.MaterialFromObject
            if not doc.Objects.ModifyAttributes(object_id, attrs, True): raise RuntimeError("attribute update failed: " + str(object_id))
            modified.append(str(object_id)); output.append(object_id)
    elif kind == "extrude_curve":
        for object_id in ids(op["targets"]):
            curve = doc.Objects.FindId(object_id).Geometry
            if not isinstance(curve, Rhino.Geometry.Curve): raise ValueError("extrude target is not a curve: " + str(object_id))
            surface = Rhino.Geometry.Surface.CreateExtrusion(curve, vector(op["vector"]))
            brep = surface.ToBrep()
            if op["cap"] and curve.IsClosed: brep = brep.CapPlanarHoles(doc.ModelAbsoluteTolerance)
            output.append(add(brep))
    elif kind == "offset_curve":
        plane = Rhino.Geometry.Plane(point([0, 0, 0]), vector(op["normal"]))
        for object_id in ids(op["targets"]):
            curve = doc.Objects.FindId(object_id).Geometry
            pieces = curve.Offset(plane, op["distance"], doc.ModelAbsoluteTolerance, Rhino.Geometry.CurveOffsetCornerStyle.Sharp)
            if not pieces: raise RuntimeError("curve offset failed: " + str(object_id))
            output.extend(add(piece) for piece in pieces)
    else:
        left_ids = ids(op["targets"]); left = [doc.Objects.FindId(i).Geometry for i in left_ids]
        if not all(isinstance(g, Rhino.Geometry.Brep) for g in left): raise ValueError("boolean targets must be Breps")
        tolerance = doc.ModelAbsoluteTolerance
        if kind == "boolean_union": result = Rhino.Geometry.Brep.CreateBooleanUnion(left, tolerance)
        elif kind == "boolean_intersection": result = Rhino.Geometry.Brep.CreateBooleanIntersection(left[0], left[1], tolerance) if len(left) == 2 else None
        else:
            right_ids = ids(op["cutters"]); right = [doc.Objects.FindId(i).Geometry for i in right_ids]
            if not all(isinstance(g, Rhino.Geometry.Brep) for g in right): raise ValueError("boolean cutters must be Breps")
            result = Rhino.Geometry.Brep.CreateBooleanDifference(left, right, tolerance)
        if not result: raise RuntimeError(kind + " produced no geometry")
        output = [add(geometry) for geometry in result]
        if op["delete_input"]:
            consumed = left_ids + (right_ids if kind == "boolean_difference" else [])
            for object_id in consumed:
                if doc.Objects.Delete(object_id, True): deleted.append(str(object_id))
    aliases[op["id"]] = output

doc.Views.Redraw()
print(json.dumps({"status":"completed","created":created,"modified":modified,"deleted":deleted,"outputs":{k:[str(v) for v in values] for k,values in aliases.items()}}, sort_keys=True))
'''
