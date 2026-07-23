"""KiCad PCB (.kicad_pcb) exporter: ForgeLab IR -> S-expression text.

Rebuilds the typed hardware vocabulary from the IR node graph and emits a
complete, functional ``kicad_pcb`` S-expression. Depends only on
``forgelab.spec`` and ``forgelab.formats`` (never on importers/exporters/core).

Coordinate frames: the IR is Y-up (see ``forgelab.spec.hardware``); KiCad
files are Y-down. This exporter therefore mirrors every absolute Y about the
board outline's vertical centre (``y_file = ymin + ymax - y_ir``; pure
negation when there is no outline) and negates pad-local Y offsets. Rotation
angles pass through unchanged: KiCad's positive rotation is counterclockwise
on screen, the same visual meaning as the IR's — the frame mirror is absorbed
by the local-offset negation. The importer applies the exact inverse, so
round-trips stay identity.
"""

from __future__ import annotations

import math

from forgelab.exporters.base import Exporter
from forgelab.formats import Symbol, dumps
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    NODE_TRACK,
    NODE_VIA,
    NODE_ZONE,
    BoardConstraints,
    Component,
    DesignRules,
    ForgeDocument,
    Net,
    Pad,
    Track,
    Via,
    Zone,
    pad_default_size,
    pad_grid_offset,
)
from forgelab.sync.hashing import HASH_KEY, document_hash

_DEFAULT_LAYERS = [
    [0, Symbol("F.Cu"), Symbol("signal")],
    [31, Symbol("B.Cu"), Symbol("signal")],
    [44, Symbol("Edge.Cuts"), Symbol("user")],
]

# KiCad zone display/fill defaults (verified against KiCad 10 template zones):
# the hatch pitch and thermal-relief geometry a fresh copper pour is created
# with. They affect only how the pour connects thermally and is drawn, not
# where copper may go — that is min_thickness plus the clearance below.
_ZONE_HATCH_PITCH = 0.5
_ZONE_THERMAL_GAP = 0.5
_ZONE_THERMAL_BRIDGE = 0.5

# Footprint text (matches the KiCad library default: 1mm glyphs, 0.15mm pen).
_TEXT_SIZE = 1.0
_TEXT_THICKNESS = 0.15
# Half the drawn height of a one-line reference designator, pen included.
_TEXT_HALF_HEIGHT = _TEXT_SIZE / 2 + _TEXT_THICKNESS / 2
# Gap left between that text and the nearest pad's solder-mask opening. KiCad's
# silk_over_copper rule fires on any overlap, so the offset only has to clear
# the copper; the extra margin keeps the silkscreen legible next to the pad.
_SILK_PAD_GAP = 0.35
# Per-character advance of KiCad's stroke font, as a fraction of the glyph box.
_TEXT_ADVANCE = 0.8
# How far, and in how many tries, a colliding reference designator is stepped
# away from the part before giving up and taking the library-convention spot.
_SILK_STEP = 0.6
_SILK_MAX_STEPS = 8


def _num(value: float) -> int | float:
    """Emit integral floats as ints so output matches KiCad's style."""
    return int(value) if float(value).is_integer() else float(value)


def _s(tag: str, *args: object) -> list:
    """Build an S-expression list headed by a bare ``tag`` symbol."""
    return [Symbol(tag), *args]


# KiCad stores a file-format version as a bare integer date stamp, never a
# quoted semantic version. Map known application versions to their format date
# and fall back to a known-good value for anything unrecognized or missing.
_DEFAULT_FORMAT_VERSION = 20221018
_SEMVER_TO_FORMAT = {
    "6.0": 20211014,
    "7.0": 20221018,
    "8.0": 20240108,
    "9.0": 20240108,
}


def _format_version(raw: str) -> int:
    """Normalize a kicad_version field to KiCad's unquoted integer date stamp."""
    text = (raw or "").strip()
    if text.isdigit():
        return int(text)
    if text in _SEMVER_TO_FORMAT:
        return _SEMVER_TO_FORMAT[text]
    major = text.split(".")[0]
    for semver, fmt in _SEMVER_TO_FORMAT.items():
        if semver.split(".")[0] == major:
            return fmt
    return _DEFAULT_FORMAT_VERSION


def _mirror_axis(outline) -> float:
    """``ymin + ymax`` of the outline: mirroring about it maps the board's Y
    range onto itself, keeping coordinates positive and round-trippable.
    Without an outline there is no board frame, so mirror about y=0."""
    ys = [float(p[1]) for seg in outline for p in (seg.start, seg.end)]
    return (min(ys) + max(ys)) if ys else 0.0


def _flip_y(y: float, axis: float) -> float:
    """IR Y-up -> KiCad Y-down (involutive; rounded so round-trips are exact)."""
    return round(axis - y, 6) + 0.0  # + 0.0 normalizes -0.0


# An axis-aligned rectangle (x0, y0, x1, y1) in the absolute KiCad frame.
_Rect = tuple[float, float, float, float]


def _rotate_local(x: float, y: float, angle: float) -> tuple[float, float]:
    """Rotate a footprint-local (Y-down) offset by the footprint's angle.

    KiCad's positive angle is counterclockwise on screen, so the rotation is
    applied in the Y-up view and mapped back down.
    """
    theta = math.radians(angle)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return x * cos_t + y * sin_t, -x * sin_t + y * cos_t


def _rotated_half_extents(width: float, height: float, angle: float) -> tuple[float, float]:
    """Half-extents of the axis-aligned bbox of a rotated w x h rectangle."""
    theta = math.radians(angle)
    cos_t, sin_t = abs(math.cos(theta)), abs(math.sin(theta))
    return (width * cos_t + height * sin_t) / 2, (width * sin_t + height * cos_t) / 2


def _overlaps(a: _Rect, b: _Rect) -> bool:
    """True when two axis-aligned rectangles share any area."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class KiCadExporter(Exporter):
    """Export ForgeLab IR to a KiCad PCB."""

    tool_name = "kicad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        board = self._board(document)
        nets = self._nets(document)
        components = self._components(document)
        name_to_code = {n.name: n.code for n in nets}
        # IR is Y-up, KiCad is Y-down: every absolute Y below goes through
        # _flip_y about the outline's vertical centre.
        axis = _mirror_axis(board.outline)

        tree: list = [Symbol("kicad_pcb")]
        tree.append(_s("version", _format_version(board.kicad_version)))
        tree.append(_s("generator", Symbol(board.generator)))
        tree.append(_s("property", HASH_KEY, document_hash(document.model_dump(mode="json"))))
        tree.append(_s("general", _s("thickness", 1.6)))
        tree.append(_s("paper", "A4"))
        tree.append(self._layers_block(board))
        tree.append(self._setup_block(board.design_rules))
        for net in sorted(nets, key=lambda n: n.code):
            tree.append(_s("net", net.code, net.name))
        tree.append(self._net_class_block(board.design_rules, nets))
        # Silkscreen text is placed around every pad on the board, not just the
        # part's own, so the obstacle set is built once up front.
        obstacles = self._pad_obstacles(components, axis)
        for comp in components:
            tree.append(self._footprint(comp, name_to_code, axis, obstacles))
        for node in document.nodes:
            if node.type == NODE_TRACK:
                track = Track.model_validate(node.props)
                tree.append(
                    _s(
                        "segment",
                        _s("start", _num(track.start[0]), _num(_flip_y(track.start[1], axis))),
                        _s("end", _num(track.end[0]), _num(_flip_y(track.end[1], axis))),
                        _s("width", _num(track.width)),
                        _s("layer", track.layer),
                        _s("net", name_to_code.get(track.net, 0)),
                    )
                )
            elif node.type == NODE_VIA:
                via = Via.model_validate(node.props)
                tree.append(
                    _s(
                        "via",
                        _s("at", _num(via.at[0]), _num(_flip_y(via.at[1], axis))),
                        _s("size", _num(via.size)),
                        _s("drill", _num(via.drill)),
                        _s("layers", "F.Cu", "B.Cu"),
                        _s("net", name_to_code.get(via.net, 0)),
                    )
                )
            elif node.type == NODE_ZONE:
                zone = Zone.model_validate(node.props)
                tree.append(self._zone(zone, name_to_code, board.design_rules, axis))
        for seg in board.outline:
            tree.append(
                _s(
                    "gr_line",
                    _s("start", _num(seg.start[0]), _num(_flip_y(seg.start[1], axis))),
                    _s("end", _num(seg.end[0]), _num(_flip_y(seg.end[1], axis))),
                    _s("stroke", _s("width", 0.1), _s("type", Symbol("solid"))),
                    _s("layer", "Edge.Cuts"),
                )
            )

        return dumps(tree).encode("utf-8")

    def _board(self, document: ForgeDocument) -> BoardConstraints:
        for node in document.nodes:
            if node.type == NODE_BOARD:
                return BoardConstraints.model_validate(node.props)
        return BoardConstraints(
            kicad_version="20240108",
            generator="forgelab",
            layers=[],
            outline=[],
            design_rules=DesignRules(
                clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4
            ),
        )

    def _nets(self, document: ForgeDocument) -> list[Net]:
        nets = [Net.model_validate(n.props) for n in document.nodes if n.type == NODE_NET]
        if not any(n.code == 0 for n in nets):
            nets.insert(0, Net(code=0, name=""))
        return nets

    def _components(self, document: ForgeDocument) -> list[Component]:
        return [
            Component.model_validate(n.props) for n in document.nodes if n.type == NODE_COMPONENT
        ]

    def _layers_block(self, board: BoardConstraints) -> list:
        entries: list = [Symbol("layers")]
        if board.layers:
            rows = [
                [
                    layer.ordinal,
                    Symbol(layer.canonical_name),
                    Symbol(layer.layer_type),
                ]
                + ([layer.user_name] if layer.user_name else [])
                for layer in board.layers
            ]
        else:
            rows = [list(row) for row in _DEFAULT_LAYERS]
        entries.extend(rows)
        return entries

    def _setup_block(self, rules: DesignRules) -> list:
        # KiCad 9 rejects design-rule keys inside (setup ...); they live in
        # net classes instead (see _net_class_block).
        return _s("setup", _s("pad_to_mask_clearance", 0))

    def _net_class_block(self, rules: DesignRules, nets: list[Net]) -> list:
        block = _s(
            "net_class",
            "Default",
            "ForgeLab default net class",
            _s("clearance", _num(rules.clearance)),
            _s("trace_width", _num(rules.track_width)),
            _s("via_dia", _num(rules.via_diameter)),
            _s("via_drill", _num(rules.via_drill)),
        )
        for net in sorted(nets, key=lambda n: n.code):
            if net.name:
                block.append(_s("add_net", net.name))
        return block

    def _placed_pads(self, comp: Component) -> list[tuple[Pad, float, float, float, float]]:
        """Resolve every pad to ``(pad, x, y, width, height)`` in footprint-local
        KiCad (Y-down) coordinates — the geometry the exporter emits, and the
        same geometry the silkscreen placement has to keep clear of."""
        total = len(comp.pads)
        # Size-less pads render the shared pitch-aware default, so the copper
        # here matches what the layout and validation tools assumed.
        default = pad_default_size([p.at for p in comp.pads if p.at is not None])
        placed: list[tuple[Pad, float, float, float, float]] = []
        for index, pad in enumerate(comp.pads):
            # Honor an explicit pad offset; otherwise spread pads on a grid so
            # a multi-pin part doesn't collapse onto the footprint origin.
            if pad.at is not None:
                # Pad-local offsets are Y-up in the IR, Y-down in KiCad:
                # negate (not mirror — this is a footprint-relative frame).
                x, y = pad.at[0], -pad.at[1] + 0.0
            else:
                # The fallback grid is computed in IR (Y-up) space — the same
                # grid the Gerber exporter uses — so its Y is negated too.
                x, y = pad_grid_offset(index, total)
                y = -y + 0.0
            width, height = (pad.size[0], pad.size[1]) if pad.size else (default, default)
            placed.append((pad, x, y, width, height))
        return placed

    def _pad_obstacles(self, components: list[Component], axis: float) -> list[_Rect]:
        """Every pad's copper as an absolute, axis-aligned rectangle in the KiCad
        frame. Silkscreen text is routed around these so it never lands on a
        pad's solder-mask opening — a ``silk_over_copper`` DRC warning."""
        rects: list[_Rect] = []
        for comp in components:
            cx, cy, angle = comp.at[0], _flip_y(comp.at[1], axis), comp.at[2]
            for _pad, x, y, width, height in self._placed_pads(comp):
                px, py = _rotate_local(x, y, angle)
                half_w, half_h = _rotated_half_extents(width, height, angle)
                rects.append(
                    (cx + px - half_w, cy + py - half_h, cx + px + half_w, cy + py + half_h)
                )
        return rects

    def _footprint(
        self,
        comp: Component,
        name_to_code: dict[str, int],
        axis: float,
        obstacles: list[_Rect],
    ) -> list:
        fp: list = [Symbol("footprint"), comp.footprint, _s("layer", comp.layer)]
        if comp.uuid is not None:
            fp.append(_s("uuid", comp.uuid))
        # Absolute Y is mirrored into KiCad's Y-down frame; the rotation angle
        # passes through (CCW-on-screen in both conventions).
        fp.append(_s("at", _num(comp.at[0]), _num(_flip_y(comp.at[1], axis)), _num(comp.at[2])))
        placed = self._placed_pads(comp)

        fp.extend(self._text_properties(comp, placed, axis, obstacles))
        for pad, x, y, width, height in placed:
            code = name_to_code.get(pad.net, 0)
            shape = pad.shape if pad.shape else "roundrect"
            if pad.drill is None:
                # SMD: copper on the component's layer only. Output unchanged.
                fp.append(
                    _s(
                        "pad",
                        pad.number,
                        Symbol("smd"),
                        Symbol(shape),
                        _s("at", _num(x), _num(y)),
                        _s("size", _num(width), _num(height)),
                        _s("layers", "F.Cu"),
                        _s("net", code, pad.net),
                    )
                )
            else:
                fp.append(self._through_hole_pad(pad, code, x, y, width, height, shape))
        return fp

    def _text_properties(
        self,
        comp: Component,
        placed: list[tuple[Pad, float, float, float, float]],
        axis: float,
        obstacles: list[_Rect],
    ) -> list[list]:
        """Reference on silkscreen clear of copper, Value on the fab layer.

        A bare ``(property "Reference" ...)`` lands at the footprint origin,
        which on a real part sits in the middle of the pad row — KiCad's DRC
        then reports ``silk_over_copper`` against every pad the text crosses.
        The KiCad libraries place the designator outside the pads instead (e.g.
        ``(at 0 -2.38 0)`` on ``F.SilkS`` for a 2.54mm header), so this offsets
        the text past the pads' bounding box by half its glyph height plus a
        gap, and then steps it further out until it also clears *every other*
        part's copper — a densely auto-placed board puts neighbours close
        enough that clearing only your own pads is not sufficient. Value goes
        to ``F.Fab``, which is not a silkscreen layer and so cannot collide
        with copper at all, again matching the library footprints.

        Coordinates are footprint-local and unrotated: KiCad rotates the text
        with the footprint, so the offset stays clear of the pads at any angle.
        """
        if placed:
            top = min(y - height / 2 for _pad, _x, y, _w, height in placed)
            bottom = max(y + height / 2 for _pad, _x, y, _w, height in placed)
        else:
            top = bottom = 0.0
        gap = _TEXT_HALF_HEIGHT + _SILK_PAD_GAP
        ref_y = self._silk_offset(comp, top - gap, bottom + gap, axis, obstacles)
        effects = _s(
            "effects",
            _s("font", _s("size", _TEXT_SIZE, _TEXT_SIZE), _s("thickness", _TEXT_THICKNESS)),
        )
        return [
            _s(
                "property",
                "Reference",
                comp.reference,
                _s("at", 0, _num(round(ref_y, 6)), 0),
                _s("layer", "F.SilkS"),
                effects,
            ),
            _s(
                "property",
                "Value",
                comp.value,
                _s("at", 0, _num(round(bottom + gap, 6)), 0),
                _s("layer", "F.Fab"),
                effects,
            ),
        ]

    def _silk_offset(
        self, comp: Component, above: float, below: float, axis: float, obstacles: list[_Rect]
    ) -> float:
        """Pick the local Y for the reference designator that clears all copper.

        Alternates above/below the part, stepping outward, and returns the first
        offset whose text rectangle touches no pad on the board. Falls back to
        the first candidate (directly above the part, the library convention) if
        nothing within ``_SILK_MAX_STEPS`` is clear — better a warning than a
        designator flung off into another part of the board.
        """
        cx, cy, angle = comp.at[0], _flip_y(comp.at[1], axis), comp.at[2]
        # KiCad's stroke font advances a little under one glyph box per
        # character; this over-estimates slightly, which is the safe direction.
        half_w = len(comp.reference) * _TEXT_SIZE * _TEXT_ADVANCE / 2
        for step in range(_SILK_MAX_STEPS):
            for candidate in (above - step * _SILK_STEP, below + step * _SILK_STEP):
                tx, ty = _rotate_local(0.0, candidate, angle)
                ex, ey = _rotated_half_extents(2 * half_w, 2 * _TEXT_HALF_HEIGHT, angle)
                rect = (cx + tx - ex, cy + ty - ey, cx + tx + ex, cy + ty + ey)
                if not any(_overlaps(rect, other) for other in obstacles):
                    return candidate
        return above

    def _through_hole_pad(
        self, pad: Pad, code: int, x: float, y: float, width: float, height: float, shape: str
    ) -> list:
        """A drilled pad: ``thru_hole``/``np_thru_hole`` spanning ``*.Cu`` + ``*.Mask``.

        Grammar verified against real KiCad 10 footprints: a plated hole is
        ``thru_hole``, a bare mechanical one ``np_thru_hole``; a round hole is
        ``(drill d)`` and a slot ``(drill oval w h)``; and the copper spans every
        layer via ``(layers "*.Cu" "*.Mask")`` — which is exactly what lets a
        copper pour or a back-side track connect to the pad.
        """
        assert pad.drill is not None
        drill = pad.drill
        pad_type = "thru_hole" if drill.plated else "np_thru_hole"
        if drill.oval is not None:
            drill_token = _s("drill", Symbol("oval"), _num(drill.oval[0]), _num(drill.oval[1]))
        else:
            # The model validator guarantees exactly one of oval/diameter is set.
            assert drill.diameter is not None
            drill_token = _s("drill", _num(drill.diameter))
        return _s(
            "pad",
            pad.number,
            Symbol(pad_type),
            Symbol(shape),
            _s("at", _num(x), _num(y)),
            _s("size", _num(width), _num(height)),
            drill_token,
            _s("layers", "*.Cu", "*.Mask"),
            _s("remove_unused_layers", Symbol("no")),
            _s("net", code, pad.net),
        )

    def _zone(
        self, zone: Zone, name_to_code: dict[str, int], rules: DesignRules, axis: float
    ) -> list:
        """A copper pour: the boundary polygon only — KiCad computes the fill.

        The grammar (net/net_name/layer/hatch/connect_pads/min_thickness/fill/
        polygon) is verified against real KiCad 10 output; ``(fill yes ...)``
        makes it a fillable solid pour rather than a keepout. Every polygon Y is
        mirrored into KiCad's Y-down frame like every other absolute coordinate.
        ``clearance`` maps to the zone's connect_pads clearance (KiCad's own
        per-zone clearance field); when unset it inherits design_rules.clearance,
        which the net class already enforces for foreign-net isolation.
        """
        clearance = zone.clearance if zone.clearance is not None else rules.clearance
        pts = _s(
            "pts",
            *(_s("xy", _num(p[0]), _num(_flip_y(p[1], axis))) for p in zone.polygon),
        )
        # ``connect_pads yes`` = a solid connection to same-net pads. A power or
        # ground plane wants solid copper, not thermal-relief spokes: thermal
        # spokes on a plane produce KiCad "starved thermal" DRC errors where a
        # pad is boxed in, and solid connection is electrically better anyway.
        return _s(
            "zone",
            _s("net", name_to_code.get(zone.net, 0)),
            _s("net_name", zone.net),
            _s("layer", zone.layer),
            _s("hatch", Symbol("edge"), _num(_ZONE_HATCH_PITCH)),
            _s("connect_pads", Symbol("yes"), _s("clearance", _num(clearance))),
            _s("min_thickness", _num(zone.min_thickness)),
            _s(
                "fill",
                Symbol("yes"),
                _s("thermal_gap", _num(_ZONE_THERMAL_GAP)),
                _s("thermal_bridge_width", _num(_ZONE_THERMAL_BRIDGE)),
            ),
            _s("polygon", pts),
        )
