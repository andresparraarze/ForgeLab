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

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NODE_PART = "part"
NODE_BODY = "body"
NODE_SKETCH = "sketch"
NODE_PAD = "pad"
NODE_POCKET = "pocket"
NODE_LOFT = "loft"
NODE_SWEEP = "sweep"
NODE_FILLET = "fillet"
NODE_SHELL = "shell"
NODE_REVOLVE = "revolve"
NODE_BOOLEAN = "boolean"


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
    """One geometry primitive in a sketch: a line segment, a circle or an arc.

    ``line`` and ``circle`` are closed-profile building blocks on their own;
    ``arc`` is an *open* curve segment — a piece of a circle — whose two
    endpoints join adjacent lines (or other arcs) to form a rounded profile:
    a rounded rectangle, a slot, a filleted 2D outline.

    Arc angles are **degrees, counter-clockwise from the +X axis**, and the arc
    always sweeps counter-clockwise from ``start_angle`` to ``end_angle``. That
    is FreeCAD's own Sketcher convention (``Part.ArcOfCircle`` takes the same
    two angles in radians), verified against FreeCAD 1.1: an arc built at
    ``(0, 90)`` around the origin with radius 5 starts at ``(5, 0)`` and ends
    at ``(0, 5)``. The endpoints therefore are::

        start = center + radius * (cos(start_angle), sin(start_angle))
        end   = center + radius * (cos(end_angle),   sin(end_angle))
    """

    model_config = ConfigDict(extra="forbid")

    geo_type: str
    points: list[float] = Field(default_factory=list)
    center: list[float] = Field(default_factory=list)
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0

    @field_validator("geo_type")
    @classmethod
    def _known_geo_type(cls, value: str) -> str:
        if value not in ("line", "circle", "arc"):
            raise ValueError("geo_type must be 'line', 'circle' or 'arc'")
        return value

    @model_validator(mode="after")
    def _check_shape(self) -> SketchGeometry:
        if self.geo_type == "line":
            if len(self.points) != 4:
                raise ValueError("line geometry needs points [x1, y1, x2, y2]")
            if self.center or self.radius:
                raise ValueError("line geometry must not set center/radius")
        elif self.geo_type == "circle":
            if len(self.center) != 2:
                raise ValueError("circle geometry needs center [x, y]")
            if self.points:
                raise ValueError("circle geometry must not set points")
        else:  # arc
            if len(self.center) != 2:
                raise ValueError("arc geometry needs center [x, y]")
            if self.points:
                raise ValueError("arc geometry must not set points")
            if self.start_angle == self.end_angle:
                raise ValueError("arc geometry needs start_angle != end_angle (zero sweep)")
            return self
        if self.start_angle or self.end_angle:
            raise ValueError(f"{self.geo_type} geometry must not set start_angle/end_angle")
        return self

    def endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """The ``(start, end)`` points of an open curve, for profile closure.

        Defined for ``line`` and ``arc``; a ``circle`` is closed on its own and
        has no endpoints to join, so it raises.
        """
        if self.geo_type == "line":
            return (self.points[0], self.points[1]), (self.points[2], self.points[3])
        if self.geo_type == "arc":
            cx, cy = self.center
            a0, a1 = math.radians(self.start_angle), math.radians(self.end_angle)
            return (
                (cx + self.radius * math.cos(a0), cy + self.radius * math.sin(a0)),
                (cx + self.radius * math.cos(a1), cy + self.radius * math.sin(a1)),
            )
        raise ValueError(f"{self.geo_type} geometry is a closed curve and has no endpoints")


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


class Loft(BaseModel):
    """A loft feature: blend a solid through ordered profile sketches (Part::Loft).

    The Part workbench (OCC kernel) computes the real NURBS surface on
    recompute — this model only carries the parametric description. ``ruled``
    False gives a smooth blended surface between profiles; True gives straight
    line segments. ``closed`` True joins the last profile back to the first.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    profiles: list[str] = Field(
        default_factory=list,
        description="Ordered sketch node ids to loft through; at least 2 are required.",
    )
    ruled: bool = False
    closed: bool = False


class Sweep(BaseModel):
    """A sweep feature: drive a profile along a path curve (Part::Sweep).

    ``frenet`` True keeps the profile orientation following the path's
    curvature naturally.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    profile: str = ""
    path: str = ""
    frenet: bool = False


class Revolve(BaseModel):
    """A revolve feature: spin a profile around an axis (Part::Revolution).

    The natural fit for axially-symmetric organic shapes — knobs, handles,
    bottle-like grips, rounded caps. ``profile`` is a closed 2D sketch drawn on
    a plane that CONTAINS the revolution axis (e.g. a sketch on the XZ plane
    revolved around Z); its geometry must stay on one side of the axis
    (touching it is fine, crossing it self-intersects). ``axis`` is the global
    X/Y/Z axis through the origin; ``angle`` in degrees supports partial
    revolves (default a full 360).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    profile: str = ""
    axis: str = "Z"
    angle: float = 360.0

    @field_validator("axis")
    @classmethod
    def _known_axis(cls, value: str) -> str:
        axis = value.strip().upper()
        if axis not in ("X", "Y", "Z"):
            raise ValueError("axis must be 'X', 'Y' or 'Z'")
        return axis


class Fillet(BaseModel):
    """A fillet feature: round the edges of a feature's solid (Part::Fillet).

    ``edges`` lists 1-based OCC edge indices on the target's shape; when it is
    omitted (None) every edge of the target is filleted — the common case for
    rounding an entire body.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    target: str = ""
    radius: float
    edges: list[int] | None = None


class Boolean(BaseModel):
    """A boolean feature: combine two independently-built solids.

    This is the only way to join geometry across bodies. Every other feature
    works inside one body's own sketch/pad/pocket/loft/revolve chain, so two
    separately-modelled solids — a base plate and a boss, a housing and a
    mounting lug — could not be merged into one shape at all.

    ``base`` and ``tools`` name other nodes: a solid feature (a pad, loft,
    revolve, another boolean) or a whole ``body``, either of which FreeCAD
    accepts as a boolean input.

    Operation-to-FreeCAD-type mapping, verified against FreeCAD 1.1 (there is
    no instantiable ``Part::Boolean`` — it is an abstract base class):

    ==========  ====================  =========================
    operation   FreeCAD type          inputs
    ==========  ====================  =========================
    union       ``Part::MultiFuse``   ``Shapes`` = base + tools
    common      ``Part::MultiCommon`` ``Shapes`` = base + tools
    cut         ``Part::Cut``         ``Base`` + a single ``Tool``
    ==========  ====================  =========================

    Union and common therefore take any number of tools in one operation.
    **Cut takes exactly one**: FreeCAD ships no ``Part::MultiCut``, so a
    multi-tool cut has no honest single-object representation — chain one
    boolean per tool instead.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    operation: str
    base: str = ""
    tools: list[str] = Field(
        default_factory=list,
        description="Node ids of the solids to combine with base; at least one.",
    )

    @field_validator("operation")
    @classmethod
    def _known_operation(cls, value: str) -> str:
        if value not in ("union", "cut", "common"):
            raise ValueError("operation must be 'union', 'cut' or 'common'")
        return value

    @model_validator(mode="after")
    def _check_inputs(self) -> Boolean:
        if not self.base:
            raise ValueError("boolean needs a base (the node id of the first solid)")
        if not self.tools:
            raise ValueError("boolean needs at least one tool")
        if self.operation == "cut" and len(self.tools) != 1:
            raise ValueError(
                "a cut takes exactly one tool (FreeCAD has no Part::MultiCut); "
                "chain one boolean per tool to cut several"
            )
        if self.base in self.tools:
            raise ValueError("boolean base must not also be one of its tools")
        return self


class Shell(BaseModel):
    """A shell feature: hollow a solid to a wall thickness (Part::Thickness).

    ``faces_to_remove`` lists 1-based OCC face indices to leave open (e.g. the
    top face of an enclosure). NOTE: FreeCAD's kernel cannot hollow a solid
    with no opening — a shell with no ``faces_to_remove`` exports but produces
    a null shape on recompute, so in practice leave at least one face open.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    target: str = ""
    thickness: float
    faces_to_remove: list[int] | None = None
