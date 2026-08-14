"""Pure adapter mapping for jingcheng-chen/rhinomcp's plugin protocol.

This module deliberately performs no I/O.  It maps the runtime's validated Rhino
operations to the *plugin TCP commands*, whose structured results preserve more
information than several of RhinoMCP's human-facing MCP wrappers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .host_contract import content_hash, finalize_scene
from .operations import normalize_operations


class RhinoMCPMappingError(ValueError):
    """An operation cannot preserve the Hermes runtime contract via RhinoMCP."""


@dataclass(frozen=True)
class RhinoMCPCommand:
    command: str
    params: dict[str, Any]
    bind: str | None = None
    result_ids_field: str | None = None


def _targets(values: Iterable[str]) -> list[str]:
    # $aliases are intentionally retained.  The transport executor resolves them
    # from prior command results immediately before sending the command.
    return list(values)


def compile_rhinomcp_commands(operations: list[Mapping[str, Any]]) -> list[RhinoMCPCommand]:
    """Compile supported typed operations to RhinoMCP plugin commands.

    Commands remain sequential because aliases may refer to IDs created earlier
    in the transaction. Unsupported operations fail closed rather than falling
    back to RhinoScript/Python/C#.
    """
    normalized = normalize_operations(operations)
    commands: list[RhinoMCPCommand] = []
    for op in normalized:
        kind, alias = op["op"], op["id"]
        if kind == "create_point":
            x, y, z = op["point"]
            params = {"type": "POINT", "params": {"x": x, "y": y, "z": z}}
            commands.append(RhinoMCPCommand("create_object", params, alias, "id"))
        elif kind == "create_line":
            params = {"type": "LINE", "params": {"start": op["start"], "end": op["end"]}}
            commands.append(RhinoMCPCommand("create_object", params, alias, "id"))
        elif kind == "create_polyline":
            points = list(op["points"])
            if op["closed"] and points[0] != points[-1]:
                points.append(points[0])
            params = {"type": "POLYLINE", "params": {"points": points}}
            commands.append(RhinoMCPCommand("create_object", params, alias, "id"))
        elif kind == "create_box":
            minimum, maximum = op["min"], op["max"]
            size = [maximum[i] - minimum[i] for i in range(3)]
            center = [(maximum[i] + minimum[i]) / 2 for i in range(3)]
            params = {"type": "BOX", "params": {"width": size[0], "length": size[1], "height": size[2]}, "translation": center}
            commands.append(RhinoMCPCommand("create_object", params, alias, "id"))
        elif kind == "create_sphere":
            params = {"type": "SPHERE", "params": {"radius": op["radius"]}, "translation": op["center"]}
            commands.append(RhinoMCPCommand("create_object", params, alias, "id"))
        elif kind == "delete":
            for target in _targets(op["targets"]):
                commands.append(RhinoMCPCommand("delete_object", {"id": target}))
        elif kind == "set_attributes":
            updates = {key: value for key, value in op.items() if key in {"layer", "color", "material_index"}}
            if "name" in op:
                updates["new_name"] = op["name"]
            for target in _targets(op["targets"]):
                commands.append(RhinoMCPCommand("update_object_attributes", {"id": target, **updates}))
        elif kind == "extrude_curve":
            for target in _targets(op["targets"]):
                commands.append(RhinoMCPCommand("extrude_curve", {"curve_id": target, "direction": op["vector"], "cap": op["cap"]}, alias, "result_id"))
        elif kind == "offset_curve":
            for target in _targets(op["targets"]):
                commands.append(RhinoMCPCommand("offset_curve", {"curve_id": target, "distance": op["distance"], "plane": op["normal"], "corner_style": 1}, alias, "result_ids"))
        elif kind in {"boolean_union", "boolean_intersection"}:
            command = kind
            commands.append(RhinoMCPCommand(command, {"object_ids": _targets(op["targets"]), "delete_sources": op["delete_input"]}, alias, "result_ids"))
        elif kind == "boolean_difference":
            if len(op["targets"]) != 1:
                raise RhinoMCPMappingError("RhinoMCP boolean_difference requires exactly one base target")
            commands.append(RhinoMCPCommand("boolean_difference", {"base_id": op["targets"][0], "subtract_ids": _targets(op["cutters"]), "delete_sources": op["delete_input"]}, alias, "result_ids"))
        elif kind == "transform_in_place":
            raise RhinoMCPMappingError(
                "RhinoMCP modify_object does not satisfy stable-ID in-place transforms; "
                "its plugin calls Objects.Transform(..., deleteOriginal: true)"
            )
        elif kind == "duplicate":
            raise RhinoMCPMappingError("RhinoMCP has no typed duplicate-object command")
        else:  # pragma: no cover - normalize_operations owns the closed set
            raise RhinoMCPMappingError(f"unsupported operation: {kind}")
    return commands


def scene_from_rhinomcp(summary: Mapping[str, Any], objects: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Normalize paginated get_objects data into the common scene contract."""
    metadata = dict(summary.get("meta_data") or {})
    normalized: list[dict[str, Any]] = []
    for raw in objects:
        item = {
            "id": str(raw.get("id") or ""), "name": raw.get("name") or "",
            "type": raw.get("type") or "UNKNOWN", "layer": raw.get("layer") or "",
            "bounding_box": raw.get("bounding_box"), "color": raw.get("color"),
            "material": raw.get("material"), "attributes": raw.get("attributes") or {},
            "geometry": raw.get("geometry"),
        }
        item["content_hash"] = content_hash(item)
        normalized.append(item)
    document_id = str(metadata.get("path") or metadata.get("name") or "active-rhino-document")
    return finalize_scene(host="rhino", document_id=document_id, units=str(metadata.get("units") or "Unknown"), objects=normalized, document={**metadata, "summary": dict(summary)})
