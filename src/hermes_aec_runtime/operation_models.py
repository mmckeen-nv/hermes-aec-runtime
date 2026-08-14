from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


Point3 = tuple[float, float, float]
Target = str


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, description="Optional alias; later operations reference it as $alias.")


class CreatePoint(_Operation):
    op: Literal["create_point"]
    point: Point3


class CreateLine(_Operation):
    op: Literal["create_line"]
    start: Point3
    end: Point3


class CreatePolyline(_Operation):
    op: Literal["create_polyline"]
    points: list[Point3] = Field(min_length=2)
    closed: bool = False


class CreateBox(_Operation):
    op: Literal["create_box"]
    min: Point3
    max: Point3


class CreateSphere(_Operation):
    op: Literal["create_sphere"]
    center: Point3
    radius: float = Field(gt=0)


class Rotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    axis: Point3
    degrees: float


class TransformInPlace(_Operation):
    op: Literal["transform_in_place"]
    targets: list[Target] = Field(min_length=1)
    translation: Point3 | None = None
    rotation: Rotation | None = None
    scale: float | None = Field(default=None, gt=0)
    center: Point3 | None = None

    @model_validator(mode="after")
    def exactly_one_transform(self) -> "TransformInPlace":
        if sum(value is not None for value in (self.translation, self.rotation, self.scale)) != 1:
            raise ValueError("provide exactly one of translation, rotation, or scale")
        return self


class Duplicate(_Operation):
    op: Literal["duplicate"]
    targets: list[Target] = Field(min_length=1)
    translation: Point3 | None = None


class Delete(_Operation):
    op: Literal["delete"]
    targets: list[Target] = Field(min_length=1)


class SetAttributes(_Operation):
    op: Literal["set_attributes"]
    targets: list[Target] = Field(min_length=1)
    name: str | None = None
    layer: str | None = None
    color: tuple[int, int, int] | None = None
    material_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def at_least_one_attribute(self) -> "SetAttributes":
        if all(value is None for value in (self.name, self.layer, self.color, self.material_index)):
            raise ValueError("provide name, layer, color, or material_index")
        return self


class ExtrudeCurve(_Operation):
    op: Literal["extrude_curve"]
    targets: list[Target] = Field(min_length=1)
    vector: Point3
    cap: bool = True


class OffsetCurve(_Operation):
    op: Literal["offset_curve"]
    targets: list[Target] = Field(min_length=1)
    distance: float
    normal: Point3 = (0.0, 0.0, 1.0)


class BooleanUnion(_Operation):
    op: Literal["boolean_union"]
    targets: list[Target] = Field(min_length=2)
    delete_input: bool = True


class BooleanIntersection(_Operation):
    op: Literal["boolean_intersection"]
    targets: list[Target] = Field(min_length=2)
    delete_input: bool = True


class BooleanDifference(_Operation):
    op: Literal["boolean_difference"]
    targets: list[Target] = Field(min_length=1, max_length=1)
    cutters: list[Target] = Field(min_length=1)
    delete_input: bool = True


RhinoOperationInput: TypeAlias = Annotated[
    Union[
        CreatePoint, CreateLine, CreatePolyline, CreateBox, CreateSphere,
        TransformInPlace, Duplicate, Delete, SetAttributes, ExtrudeCurve,
        OffsetCurve, BooleanUnion, BooleanIntersection, BooleanDifference,
    ],
    Field(discriminator="op"),
]


def dump_operations(operations: list[RhinoOperationInput] | None) -> list[dict]:
    """Convert FastMCP-validated models while preserving direct-call compatibility."""
    return [
        operation.model_dump(exclude_none=True) if isinstance(operation, BaseModel) else dict(operation)
        for operation in (operations or [])
    ]
