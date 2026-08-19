from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


Point3 = tuple[float, float, float]
Color4 = tuple[float, float, float, float]


class _BlenderOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, description="Optional unique operation alias.")


class ImportScene(_BlenderOperation):
    op: Literal["import_scene"]
    path: str
    collection: str = "AEC Import"
    source_host: Literal["rhino"] = "rhino"
    unit_scale: float = Field(default=1.0, gt=0)


class EnsureCollection(_BlenderOperation):
    op: Literal["ensure_collection"]
    name: str


class Transform(_BlenderOperation):
    op: Literal["transform"]
    objects: list[str] = Field(min_length=1)
    location: Point3 | None = None
    rotation_degrees: Point3 | None = None
    scale: Point3 | None = None

    @model_validator(mode="after")
    def has_transform(self) -> "Transform":
        if all(value is None for value in (self.location, self.rotation_degrees, self.scale)):
            raise ValueError("provide location, rotation_degrees, or scale")
        return self


class DeleteObjects(_BlenderOperation):
    op: Literal["delete_objects"]
    objects: list[str] = Field(min_length=1)


class AssignMaterial(_BlenderOperation):
    op: Literal["assign_material"]
    objects: list[str] = Field(min_length=1)
    material: str
    base_color: Color4 = (0.8, 0.8, 0.8, 1.0)
    metallic: float = Field(default=0.0, ge=0, le=1)
    roughness: float = Field(default=0.5, ge=0, le=1)


class CreateCamera(_BlenderOperation):
    op: Literal["create_camera"]
    name: str
    location: Point3
    target: Point3 | None = Field(default=None, description="World-space point the camera looks at.")
    rotation_degrees: Point3 | None = Field(default=None, description="XYZ Euler rotation; omit when target is supplied.")
    lens_mm: float = Field(default=50.0, gt=0)

    @model_validator(mode="after")
    def target_or_rotation(self) -> "CreateCamera":
        if self.target is not None and self.rotation_degrees is not None:
            raise ValueError("provide target or rotation_degrees, not both")
        return self


class CreateLight(_BlenderOperation):
    op: Literal["create_light"]
    name: str
    type: Literal["POINT", "SUN", "SPOT", "AREA"] = "AREA"
    location: Point3 = (0.0, 0.0, 0.0)
    rotation_degrees: Point3 = (0.0, 0.0, 0.0)
    energy: float = Field(default=1000.0, gt=0)


class RenderSettings(_BlenderOperation):
    op: Literal["render_settings"]
    engine: Literal["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH", "CYCLES"] = "BLENDER_EEVEE_NEXT"
    resolution: tuple[int, int] = (1920, 1080)
    samples: int = Field(default=64, gt=0)


class SaveBlend(_BlenderOperation):
    op: Literal["save_blend"]
    path: str


class Render(_BlenderOperation):
    op: Literal["render"]
    path: str


class PresentScene(_BlenderOperation):
    op: Literal["present_scene"]


BlenderOperationInput: TypeAlias = Annotated[
    Union[
        ImportScene, EnsureCollection, Transform, DeleteObjects, AssignMaterial,
        CreateCamera, CreateLight, RenderSettings, SaveBlend, Render, PresentScene,
    ],
    Field(discriminator="op"),
]


def dump_blender_operations(operations: list[BlenderOperationInput]) -> list[dict]:
    return [
        operation.model_dump(exclude_none=True) if isinstance(operation, BaseModel) else dict(operation)
        for operation in operations
    ]
