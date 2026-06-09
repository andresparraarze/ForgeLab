"""Typed mechanical-CAD (FreeCAD) vocabulary for the ForgeLab IR.

These models describe FreeCAD PartDesign concepts — parts, bodies, sketches,
and parametric features (pad/extrusion, pocket/cut) — plus the sketch geometry
and dimensional constraints that drive them. Like the hardware and 3D
vocabularies they are not a new document root: they serialize into the generic
``Node`` graph. The object graph is flat and document-ordered; assembly and
feature relationships are expressed as link references stored in ``props``
(e.g. ``body.part``, ``pad.profile``).

NOTE: these models are imported from this submodule (``forgelab.spec.mechanical``),
not re-exported from ``forgelab.spec``, because ``Pad`` would collide with the
hardware ``Pad`` already exported there.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NODE_PART = "part"
NODE_BODY = "body"
NODE_SKETCH = "sketch"
NODE_PAD = "pad"
NODE_POCKET = "pocket"


class Placement(BaseModel):
    """A rigid placement: translation + rotation quaternion [x, y, z, w]."""

    model_config = ConfigDict(extra="forbid")

    position: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])

    @field_validator("position")
    @classmethod
    def _position_is_vec3(cls, value: list[float]) -> list[float]:
        if len(value) != 3:
            raise ValueError("position must be [x, y, z]")
        return value

    @field_validator("rotation")
    @classmethod
    def _rotation_is_quat(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("rotation must be a quaternion [x, y, z, w]")
        return value


class Part(BaseModel):
    """An assembly container (App::Part)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    placement: Placement = Field(default_factory=Placement)


class Body(BaseModel):
    """A solid body (PartDesign::Body), optionally inside a Part."""

    model_config = ConfigDict(extra="forbid")

    name: str
    part: str = ""
    placement: Placement = Field(default_factory=Placement)


class SketchGeometry(BaseModel):
    """One geometry primitive in a sketch: a line segment or a circle."""

    model_config = ConfigDict(extra="forbid")

    geo_type: str
    points: list[float] = Field(default_factory=list)
    center: list[float] = Field(default_factory=list)
    radius: float = 0.0

    @field_validator("geo_type")
    @classmethod
    def _known_geo_type(cls, value: str) -> str:
        if value not in ("line", "circle"):
            raise ValueError("geo_type must be 'line' or 'circle'")
        return value

    @model_validator(mode="after")
    def _check_shape(self) -> SketchGeometry:
        if self.geo_type == "line":
            if len(self.points) != 4:
                raise ValueError("line geometry needs points [x1, y1, x2, y2]")
            if self.center or self.radius:
                raise ValueError("line geometry must not set center/radius")
        else:  # circle
            if len(self.center) != 2:
                raise ValueError("circle geometry needs center [x, y]")
            if self.points:
                raise ValueError("circle geometry must not set points")
        return self


class Constraint(BaseModel):
    """A dimensional constraint (a sketch dimension)."""

    model_config = ConfigDict(extra="forbid")

    ctype: str
    value: float
    name: str = ""


class Sketch(BaseModel):
    """A sketch: geometry primitives + dimensional constraints on a plane."""

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    plane: str = "XY_Plane"
    placement: Placement = Field(default_factory=Placement)
    geometry: list[SketchGeometry] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)


class Pad(BaseModel):
    """A pad feature: extrude a sketch profile by a length (PartDesign::Pad)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    profile: str = ""
    length: float
    reversed: bool = False
    midplane: bool = False


class Pocket(BaseModel):
    """A pocket feature: cut a sketch profile into a body (PartDesign::Pocket)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    profile: str = ""
    length: float = 0.0
    through_all: bool = False
    reversed: bool = False
    midplane: bool = False
