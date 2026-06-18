"""Typed hardware (PCB) vocabulary for the ForgeLab IR.

These models describe printed-circuit-board concepts — components, pads, nets,
layers, and board constraints. They are not a new document root: they serialize
into the generic ``Node`` graph (see the node-type constants). Importers build
these models and store ``model_dump()`` in ``Node.props``; exporters rebuild
them with ``model_validate(node.props)``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

NODE_COMPONENT = "component"
NODE_NET = "net"
NODE_BOARD = "board"


class Pad(BaseModel):
    """A single pad on a component: its net, and its physical placement.

    ``at`` is the pad's [x, y] offset from the footprint origin (millimetres).
    Real packages spread their pads across the footprint, so each pad of a
    multi-pin component should carry a distinct ``at``; when it is omitted the
    KiCad exporter lays pads out on a deterministic grid so they never collapse
    onto the origin.
    """

    model_config = ConfigDict(extra="forbid")

    number: str
    net: str = ""
    at: list[float] | None = Field(
        default=None,
        description=(
            "Physical [x, y] offset of this pad from the footprint origin, in "
            "millimetres. Specify it whenever the package geometry is known so "
            "pads land at their real positions; if omitted, the exporter spreads "
            "pads on a grid so they do not stack at the origin."
        ),
    )
    size: list[float] | None = Field(
        default=None,
        description="Optional [width, height] of the pad copper, in millimetres.",
    )
    shape: str | None = Field(
        default=None,
        description="Optional pad shape, e.g. 'roundrect', 'rect', 'circle', 'oval'.",
    )

    @field_validator("at", "size")
    @classmethod
    def _is_xy(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and len(value) != 2:
            raise ValueError("pad at/size must be [x, y]")
        return value


class Component(BaseModel):
    """A placed footprint on the board."""

    model_config = ConfigDict(extra="forbid")

    reference: str
    value: str
    footprint: str
    layer: str
    at: list[float]
    pads: list[Pad] = Field(default_factory=list)
    uuid: str | None = None

    @field_validator("at")
    @classmethod
    def _at_is_xyr(cls, value: list[float]) -> list[float]:
        if len(value) != 3:
            raise ValueError("at must be [x, y, rotation]")
        return value


class Net(BaseModel):
    """A named electrical net."""

    model_config = ConfigDict(extra="forbid")

    code: int
    name: str


class BoardLayer(BaseModel):
    """One entry in the board's layer stack."""

    model_config = ConfigDict(extra="forbid")

    ordinal: int
    canonical_name: str
    layer_type: str
    user_name: str | None = None


class OutlineSegment(BaseModel):
    """A straight segment of the board outline (Edge.Cuts)."""

    model_config = ConfigDict(extra="forbid")

    start: list[float]
    end: list[float]

    @field_validator("start", "end")
    @classmethod
    def _is_xy(cls, value: list[float]) -> list[float]:
        if len(value) != 2:
            raise ValueError("outline point must be [x, y]")
        return value


class DesignRules(BaseModel):
    """Core board design rules."""

    model_config = ConfigDict(extra="forbid")

    clearance: float
    track_width: float
    via_diameter: float
    via_drill: float


class BoardConstraints(BaseModel):
    """Document-level board constraints: stack, outline, and rules."""

    model_config = ConfigDict(extra="forbid")

    kicad_version: str
    generator: str
    layers: list[BoardLayer] = Field(default_factory=list)
    outline: list[OutlineSegment] = Field(default_factory=list)
    design_rules: DesignRules
