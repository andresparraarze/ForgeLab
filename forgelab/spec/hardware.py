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
NODE_ZONE = "zone"

# Narrowest poured copper (mm) a zone may keep: slivers thinner than this are
# unmanufacturable, so KiCad drops them. Matches KiCad's own default.
DEFAULT_ZONE_MIN_THICKNESS = 0.25

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


def _orient(p: list[float], q: list[float], r: list[float]) -> float:
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def _on_segment(p: list[float], q: list[float], r: list[float]) -> bool:
    """Is ``q`` inside the bounding box of segment ``pr`` (used when collinear)?"""
    return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])


def _segments_intersect(p1: list[float], p2: list[float], p3: list[float], p4: list[float]) -> bool:
    """True if segments p1p2 and p3p4 cross or touch (collinear overlap included)."""
    d1, d2 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    d3, d4 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4):
        return True
    return (
        (d1 == 0 and _on_segment(p3, p1, p4))
        or (d2 == 0 and _on_segment(p3, p2, p4))
        or (d3 == 0 and _on_segment(p1, p3, p2))
        or (d4 == 0 and _on_segment(p1, p4, p2))
    )


class Zone(BaseModel):
    """A filled copper pour bounded by a polygon on one layer.

    Every real 2-layer board carries power and ground as filled zones, not
    individual traces. ``polygon`` is the pour boundary in the IR's Y-up board
    frame (millimetres, origin at the outline's lower-left corner); it needs at
    least three points and must be a simple (non-self-intersecting) polygon.

    The KiCad exporter emits the boundary only; **KiCad computes the actual
    poured copper** (clearing foreign nets, thermally relieving same-net pads).
    ForgeLab does not precompute the fill — that would mean reimplementing
    KiCad's pour algorithm and drifting from what KiCad actually renders.

    ``clearance`` is the pour's local clearance in millimetres — KiCad stores it
    as the zone's ``connect_pads`` clearance. ``None`` means inherit the board's
    ``design_rules.clearance`` (the usual case); the foreign-net isolation
    clearance always comes from the net class, which the exporter writes from
    the same design rule. ``min_thickness`` is the narrowest copper the pour may
    keep.
    """

    model_config = ConfigDict(extra="forbid")

    net: str
    layer: str = "F.Cu"
    polygon: list[list[float]]
    clearance: float | None = Field(
        default=None,
        description=(
            "Pour clearance in millimetres; if omitted, the board's design_rules.clearance is used."
        ),
    )
    min_thickness: float = DEFAULT_ZONE_MIN_THICKNESS

    @field_validator("polygon")
    @classmethod
    def _is_simple_polygon(cls, value: list[list[float]]) -> list[list[float]]:
        if len(value) < 3:
            raise ValueError("zone polygon needs at least 3 points")
        for point in value:
            if len(point) != 2:
                raise ValueError("zone polygon points must be [x, y]")
        n = len(value)
        edges = [(value[i], value[(i + 1) % n]) for i in range(n)]
        # A simple polygon has no two non-adjacent edges touching or crossing.
        for i in range(n):
            a1, a2 = edges[i]
            for j in range(i + 1, n):
                # Skip edges that share a vertex (adjacent, incl. last↔first).
                if j == i or (j + 1) % n == i or (i + 1) % n == j:
                    continue
                b1, b2 = edges[j]
                if _segments_intersect(a1, a2, b1, b2):
                    raise ValueError("zone polygon must be simple (edges must not self-intersect)")
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
