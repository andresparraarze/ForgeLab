"""Typed hardware (PCB) vocabulary for the ForgeLab IR.

These models describe printed-circuit-board concepts — components, pads, nets,
layers, and board constraints. They are not a new document root: they serialize
into the generic ``Node`` graph (see the node-type constants). Importers build
these models and store ``model_dump()`` in ``Node.props``; exporters rebuild
them with ``model_validate(node.props)``.

Coordinate convention (normative for the whole hardware domain): all positions
are millimetres in a **Y-up, right-handed frame with the origin at the board
outline's lower-left corner** — +X right, +Y up, exactly how a human reasons
about parts on a bench (and how ``calculate_board_layout`` has always been
documented). Rotations are degrees, **positive = counterclockwise**. Format
tools translate at the boundary, never inside the IR: Gerber output is
natively Y-up and passes coordinates through unchanged; KiCad files are
Y-down, so the KiCad exporter/importer mirror Y about the outline's vertical
centre (and negate pad-local Y offsets) on the way in and out.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

NODE_COMPONENT = "component"
NODE_NET = "net"
NODE_BOARD = "board"
NODE_TRACK = "track"
NODE_VIA = "via"

# Copper size (mm, square) assumed for a pad that carries no explicit ``size``.
# This is the single source of truth for "invented" pad copper: the KiCad and
# Gerber exporters render it, and the layout/validation tools treat it as a
# real obstacle, so every view of the board agrees on where copper is.
DEFAULT_PAD_SIZE = 1.6

# A size-less pad can never be assumed smaller than this (mm): below ~0.3mm
# the copper stops being a manufacturable SMD pad at all.
_MIN_DEFAULT_PAD_SIZE = 0.3

# Edge-to-edge copper gap (mm) the pitch-derived default preserves between
# neighbouring pads, so invented copper never overlaps or touches.
_DEFAULT_PAD_GAP = 0.3

# Pitch (mm) of the deterministic fallback grid used for pads that carry no
# physical ``at`` offset. Shared by both exporters and the layout tools so a
# fallback pad occupies the same spot in every rendering.
PAD_GRID_PITCH = 2.0


def pad_default_size(pad_offsets: Iterable[object]) -> float:
    """Square copper size (mm) assumed for this component's size-less pads.

    A fixed default of ``DEFAULT_PAD_SIZE`` overlaps neighbouring pads on
    fine-pitch parts (1.6mm copper at a QFP's 0.8mm pitch shorts every
    adjacent pin), so the default adapts to the component's tightest pad
    pitch: ``min(DEFAULT_PAD_SIZE, min_pitch - 0.3)``, floored at 0.3mm.
    ``pad_offsets`` are the component's known pad ``at`` offsets; with fewer
    than two positioned pads there is no pitch to measure and the full
    default applies. Deterministic, and used identically by the exporters
    (which render this copper) and the layout/validation tools (which route
    around and check it).
    """
    points = [
        (float(at[0]), float(at[1]))
        for at in pad_offsets
        if isinstance(at, (list, tuple)) and len(at) == 2
    ]
    pitch: float | None = None
    for i, p in enumerate(points):
        for q in points[i + 1 :]:
            d = math.dist(p, q)
            if d > 1e-9 and (pitch is None or d < pitch):
                pitch = d
    if pitch is None:
        return DEFAULT_PAD_SIZE
    return round(min(DEFAULT_PAD_SIZE, max(_MIN_DEFAULT_PAD_SIZE, pitch - _DEFAULT_PAD_GAP)), 3)


def pad_grid_offset(index: int, total: int) -> tuple[float, float]:
    """Deterministic (x, y) offset for a pad that carries no explicit ``at``.

    Lays pads out on a centred square-ish grid so a multi-pin part never
    collapses onto the footprint origin. Purely a placement fallback — agents
    should supply real offsets via ``Pad.at`` when the package geometry is
    known. Shared by the KiCad and Gerber exporters and the layout tools so
    fallback copper lands at the same IR position in every view.
    """
    cols = max(1, math.ceil(math.sqrt(total)))
    row, col = divmod(index, cols)
    rows = math.ceil(total / cols)
    x = (col - (cols - 1) / 2) * PAD_GRID_PITCH
    y = (row - (rows - 1) / 2) * PAD_GRID_PITCH
    return x, y


class Pad(BaseModel):
    """A single pad on a component: its net, and its physical placement.

    ``at`` is the pad's [x, y] offset from the footprint origin (millimetres),
    in the IR's Y-up frame: +Y is toward the top of the board. (KiCad stores
    pad offsets Y-down; its importer/exporter negate the local Y at the file
    boundary.)
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
    """A placed footprint on the board.

    ``at`` is ``[x, y]`` or ``[x, y, rotation]``: millimetres in the IR's Y-up
    frame (origin at the board outline's lower-left corner, +Y up), rotation
    in degrees counterclockwise. The KiCad exporter flips Y into KiCad's
    Y-down file frame; Gerber output uses these values as-is.
    """

    model_config = ConfigDict(extra="forbid")

    reference: str
    value: str
    footprint: str
    layer: str
    at: list[float]
    pads: list[Pad] = Field(default_factory=list)
    uuid: str | None = None
    locked: bool = Field(
        default=False,
        description=(
            "When true, automatic placement (auto_place) keeps this component "
            "at its current 'at' position and packs the other components "
            "around it as an obstacle — e.g. a connector manually placed on a "
            "board edge."
        ),
    )

    @field_validator("at")
    @classmethod
    def _at_is_xyr(cls, value: list[float]) -> list[float]:
        # [x, y] is accepted as shorthand for [x, y, 0]: an implicit zero rotation.
        if len(value) == 2:
            return [value[0], value[1], 0.0]
        if len(value) != 3:
            raise ValueError("at must be [x, y] or [x, y, rotation]")
        return value


class Net(BaseModel):
    """A named electrical net."""

    model_config = ConfigDict(extra="forbid")

    code: int
    name: str


class Track(BaseModel):
    """One routed copper trace segment on a single layer.

    Straight line from ``start`` to ``end`` (board coordinates: millimetres,
    Y-up, origin at the outline's lower-left corner).
    Typically produced by the ``route_board`` autorouter, but agents may also
    hand-place tracks. ``width`` defaults to ``design_rules.track_width`` when
    generated by the router.
    """

    model_config = ConfigDict(extra="forbid")

    net: str
    layer: str = "F.Cu"
    start: list[float]
    end: list[float]
    width: float

    @field_validator("start", "end")
    @classmethod
    def _is_xy(cls, value: list[float]) -> list[float]:
        if len(value) != 2:
            raise ValueError("track start/end must be [x, y]")
        return value


class Via(BaseModel):
    """A plated through-hole connecting copper layers at one point.

    ``at`` is ``[x, y]`` in the IR's Y-up board frame (millimetres).
    """

    model_config = ConfigDict(extra="forbid")

    at: list[float]
    net: str
    size: float
    drill: float

    @field_validator("at")
    @classmethod
    def _is_xy(cls, value: list[float]) -> list[float]:
        if len(value) != 2:
            raise ValueError("via at must be [x, y]")
        return value


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
    drill_size: float | None = Field(
        default=None,
        description="Smallest mechanical drill (hole) size on the board, in millimetres.",
    )


class BoardConstraints(BaseModel):
    """Document-level board constraints: stack, outline, and rules.

    ``outline`` points are millimetres in the IR's Y-up frame; the outline's
    bounding box defines the board frame other coordinates live in (its
    lower-left corner is the conventional origin).
    """

    model_config = ConfigDict(extra="forbid")

    kicad_version: str
    generator: str
    layers: list[BoardLayer] = Field(default_factory=list)
    outline: list[OutlineSegment] = Field(default_factory=list)
    design_rules: DesignRules
