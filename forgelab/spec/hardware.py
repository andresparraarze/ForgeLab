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
    """A single pad on a component, and the net it connects to."""

    model_config = ConfigDict(extra="forbid")

    number: str
    net: str = ""


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
