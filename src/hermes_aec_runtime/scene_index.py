"""Compact, versioned Rhino scene audit and focused in-memory queries.

The audit is deliberately read-only and bounded.  Rhino is asked for one JSON
payload; subsequent targeting happens locally without more fragile MCP calls.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from math import dist
from typing import Any, Iterable, Mapping

SCENE_SCHEMA_VERSION = "rhino-scene-index/1.0"
AUDIT_MARKER = "HERMES_AEC_SCENE="


class SceneIndexError(ValueError):
    """A Rhino audit payload does not satisfy the scene contract."""


@dataclass(frozen=True)
class Bounds:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | Iterable[Iterable[float]]) -> "Bounds":
        if isinstance(value, Mapping):
            points = value.get("min"), value.get("max")
        else:
            points = tuple(value)
        if len(points) != 2 or any(point is None or len(point) != 3 for point in points):
            raise SceneIndexError("bounds must contain three-coordinate min and max points")
        return cls(tuple(float(v) for v in points[0]), tuple(float(v) for v in points[1]))

    @property
    def center(self) -> tuple[float, float, float]:
        return tuple((low + high) / 2 for low, high in zip(self.minimum, self.maximum))  # type: ignore[return-value]

    def intersects(self, other: "Bounds") -> bool:
        return all(a0 <= b1 and a1 >= b0 for a0, a1, b0, b1 in zip(self.minimum, self.maximum, other.minimum, other.maximum))

    def inside(self, other: "Bounds") -> bool:
        return all(b0 <= a0 and a1 <= b1 for a0, a1, b0, b1 in zip(self.minimum, self.maximum, other.minimum, other.maximum))


@dataclass(frozen=True)
class SceneIndex:
    """Validated scene payload with cheap selectors for model targeting."""

    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        required = ("schema_version", "document_revision", "units", "tolerance", "objects", "layers", "relationships")
        missing = [key for key in required if key not in self.payload]
        if missing:
            raise SceneIndexError("scene payload missing: " + ", ".join(missing))
        if self.payload["schema_version"] != SCENE_SCHEMA_VERSION:
            raise SceneIndexError(f"unsupported scene schema: {self.payload['schema_version']!r}")
        if not isinstance(self.payload["objects"], list):
            raise SceneIndexError("objects must be a list")

    @property
    def document_revision(self) -> str:
        return str(self.payload["document_revision"])

    def query(
        self,
        *,
        ids: Iterable[str] | None = None,
        name: str | None = None,
        layer: str | None = None,
        kind: str | None = None,
        visible: bool | None = None,
        locked: bool | None = None,
        near: Iterable[float] | None = None,
        radius: float | None = None,
        inside: Bounds | Mapping[str, Any] | Iterable[Iterable[float]] | None = None,
        intersects: Bounds | Mapping[str, Any] | Iterable[Iterable[float]] | None = None,
        related_to: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return compact objects matching exact attributes and AABB selectors.

        ``name`` and ``layer`` accept case-insensitive shell wildcards. A plain
        value is treated as an exact match. ``near`` measures bounding-box center.
        """
        if limit < 1:
            return []
        wanted_ids = set(ids) if ids is not None else None
        inside_bounds = inside if isinstance(inside, Bounds) else Bounds.from_value(inside) if inside is not None else None
        intersection_bounds = intersects if isinstance(intersects, Bounds) else Bounds.from_value(intersects) if intersects is not None else None
        near_point = tuple(float(v) for v in near) if near is not None else None
        if near_point is not None and len(near_point) != 3:
            raise SceneIndexError("near must have three coordinates")
        if near_point is not None and radius is None:
            raise SceneIndexError("near requires radius")
        related_ids = None
        if related_to:
            related_ids = {
                edge["target"] if edge.get("source") == related_to else edge["source"]
                for edge in self.payload["relationships"]
                if related_to in (edge.get("source"), edge.get("target"))
            }

        matches: list[dict[str, Any]] = []
        for item in self.payload["objects"]:
            if wanted_ids is not None and item.get("id") not in wanted_ids:
                continue
            if name and not _match(item.get("name", ""), name):
                continue
            if layer and not _match(item.get("layer", ""), layer):
                continue
            if kind and str(item.get("kind", "")).casefold() != kind.casefold():
                continue
            if visible is not None and bool(item.get("visible")) != visible:
                continue
            if locked is not None and bool(item.get("locked")) != locked:
                continue
            if related_ids is not None and item.get("id") not in related_ids:
                continue
            bounds = Bounds.from_value(item["bounds"])
            if near_point is not None and dist(bounds.center, near_point) > float(radius):
                continue
            if inside_bounds and not bounds.inside(inside_bounds):
                continue
            if intersection_bounds and not bounds.intersects(intersection_bounds):
                continue
            matches.append(dict(item))
            if len(matches) == limit:
                break
        return matches


def _match(value: str, pattern: str) -> bool:
    value, pattern = value.casefold(), pattern.casefold()
    return fnmatch.fnmatchcase(value, pattern) if any(char in pattern for char in "*?[") else value == pattern


def build_rhino_audit_script(*, limit: int = 2000) -> str:
    """Generate the bounded, read-only Python script sent through Rhino MCP."""
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be between 1 and 10000")
    # Keep imports and APIs compatible with Rhino 8's embedded Python.
    return f'''import hashlib, json
doc = __rhino_doc__
limit = {limit}
objects = []
relationships = []
layer_names = set()
audit_errors = []
for obj in doc.Objects:
    if len(objects) >= limit:
        break
    try:
        geometry = obj.Geometry
        if geometry is None:
            continue
        bbox = geometry.GetBoundingBox(True)
        if not bbox.IsValid:
            continue
        oid = str(obj.Id)
        layer = doc.Layers[obj.Attributes.LayerIndex]
        layer_name = layer.FullPath if layer is not None else ""
        layer_names.add(layer_name)
        group_values = obj.Attributes.GetGroupList()
        groups = [str(i) for i in group_values] if group_values else []
        row = {{
            "id": oid,
            "name": obj.Attributes.Name or "",
            "kind": geometry.ObjectType.ToString(),
            "layer": layer_name,
            "visible": bool(obj.Visible),
            "locked": bool(obj.IsLocked),
            "bounds": {{"min": [bbox.Min.X, bbox.Min.Y, bbox.Min.Z], "max": [bbox.Max.X, bbox.Max.Y, bbox.Max.Z]}},
            "groups": groups,
        }}
        content_source = [
            row["kind"], row["name"], row["layer"], row["visible"], row["locked"],
            row["bounds"], groups, int(geometry.GetHashCode()),
            int(obj.Attributes.ObjectColor.ToArgb()), int(obj.Attributes.MaterialIndex),
        ]
        row["content_hash"] = hashlib.sha256(json.dumps(content_source, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        objects.append(row)
        relationships.append({{"type": "on_layer", "source": oid, "target": "layer:" + layer_name}})
        for group in groups:
            relationships.append({{"type": "in_group", "source": oid, "target": "group:" + group}})
        instance_definition = getattr(obj, "InstanceDefinition", None)
        if instance_definition is not None:
            relationships.append({{"type": "instance_of", "source": oid, "target": "block:" + str(instance_definition.Id)}})
    except Exception as exc:
        audit_errors.append({{"id": str(getattr(obj, "Id", "unknown")), "error": str(exc)[:240]}})
all_count = sum(1 for _ in doc.Objects)
revision_source = json.dumps(objects, sort_keys=True, separators=(",", ":"))
revision = "%s:%s:%s" % (doc.RuntimeSerialNumber, all_count, hashlib.sha256(revision_source.encode("utf-8")).hexdigest()[:16])
doc_bbox = None
if objects:
    doc_bbox = {{
        "min": [min(o["bounds"]["min"][i] for o in objects) for i in range(3)],
        "max": [max(o["bounds"]["max"][i] for o in objects) for i in range(3)],
    }}
payload = {{
    "schema_version": "{SCENE_SCHEMA_VERSION}",
    "document_revision": revision,
    "document": {{"id": str(doc.RuntimeSerialNumber), "name": doc.Name or "", "path": doc.Path or ""}},
    "units": str(doc.ModelUnitSystem),
    "tolerance": float(doc.ModelAbsoluteTolerance),
    "bounds": doc_bbox,
    "objects": objects,
    "layers": sorted(layer_names),
    "relationships": relationships,
    "count": len(objects),
    "total_count": all_count,
    "truncated": all_count > len(objects),
    "audit_errors": audit_errors[:25],
}}
print("{AUDIT_MARKER}" + json.dumps(payload, separators=(",", ":")))
'''


def parse_rhino_audit_output(output: str | Mapping[str, Any]) -> SceneIndex:
    """Extract and validate an audit from MCP stdout or its decoded envelope."""
    if isinstance(output, Mapping):
        output = str(output.get("stdout", ""))
    marker_line = next((line for line in reversed(output.splitlines()) if line.startswith(AUDIT_MARKER)), None)
    if marker_line is None:
        raise SceneIndexError("Rhino audit marker not found")
    try:
        payload = json.loads(marker_line[len(AUDIT_MARKER):])
    except json.JSONDecodeError as exc:
        raise SceneIndexError(f"invalid Rhino audit JSON: {exc}") from exc
    return SceneIndex(payload)
