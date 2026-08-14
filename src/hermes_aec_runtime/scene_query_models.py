from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RhinoSceneQuery(BaseModel):
    """Bounded selector for model-facing Rhino scene reads."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["summary", "objects", "layers"] = Field(
        default="summary",
        description="summary is compact and is the required first read; objects returns bounded records; layers returns layer counts.",
    )
    ids: list[str] | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=200, description="Case-insensitive name substring.")
    layer: str | None = Field(default=None, max_length=200, description="Case-insensitive layer substring.")
    kind: str | None = Field(default=None, max_length=80, description="Exact Rhino geometry type.")
    limit: int = Field(default=25, ge=1, le=100)
    include_geometry: bool = Field(
        default=False,
        description="Include verbose geometry payloads only when coordinates are required.",
    )


def normalize_scene_query(query: RhinoSceneQuery | dict | None) -> RhinoSceneQuery:
    if isinstance(query, RhinoSceneQuery):
        return query
    return RhinoSceneQuery.model_validate(query or {})
