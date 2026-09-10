"""KiCad PCB (.kicad_pcb) importer: S-expression text -> ForgeLab IR.

Parses the KiCad board file into the typed hardware vocabulary and stores each
component/net/board as a node in the generic IR graph. Depends only on
``forgelab.spec`` and ``forgelab.formats`` (never on importers/exporters/core).

Coordinate frames: KiCad files are Y-down, the IR is Y-up (see
``forgelab.spec.hardware``). This importer mirrors every absolute Y about the
Edge.Cuts outline's vertical centre (``y_ir = ymin + ymax - y_file``; pure
negation when the file has no outline) and negates pad-local Y offsets —
the exact inverse of the exporter's flip, so round-trips stay identity.
Rotation angles pass through (CCW-on-screen in both conventions).
"""

from __future__ import annotations

from typing import Any

from forgelab.formats import SExprError, parse
from forgelab.importers.base import Importer
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    NODE_TRACK,
    NODE_VIA,
    NODE_ZONE,
    BoardConstraints,
    BoardLayer,
    Component,
    DesignRules,
    DocumentMeta,
    Domain,
    Drill,
    ForgeDocument,
    Net,
    Node,
    OutlineSegment,
    Pad,
    Track,
    Via,
    Zone,
)
from forgelab.spec.version import SPEC_VERSION


class KiCadParseError(SExprError):
    """Raised when a document is not a valid KiCad PCB."""


def _find_all(node: list, tag: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == tag]


def _find(node: list, tag: str) -> list | None:
    found = _find_all(node, tag)
    return found[0] if found else None


def _value(node: list, tag: str, default: Any = None) -> Any:
    child = _find(node, tag)
    if child is None or len(child) < 2:
        return default
    return child[1]


def _floats(values: list) -> list[float]:
    return [float(v) for v in values]


#: Every graphic a board outline can be drawn with. Reading only ``gr_line``
#: made the mirror axis wrong on any board with a rounded or chamfered edge —
#: and wrong by a constant, so *every* imported coordinate shifted, silently.
_OUTLINE_TAGS = ("gr_line", "gr_arc", "gr_rect", "gr_poly", "gr_curve", "gr_circle")


def _outline_points(tree: list) -> list[tuple[float, float]]:
    """Every (x, y) drawn on Edge.Cuts, whatever shape states it."""
    points: list[tuple[float, float]] = []
    for tag in _OUTLINE_TAGS:
        for shape in _find_all(tree, tag):
            if _value(shape, "layer") != "Edge.Cuts":
                continue
            points.extend(_shape_points(shape))
    return points


def _shape_points(shape: list) -> list[tuple[float, float]]:
    found: list[tuple[float, float]] = []
    for item in shape:
        if not isinstance(item, list) or not item:
            continue
        tag = str(item[0])
        if tag in ("start", "end", "mid", "center", "xy") and len(item) >= 3:
            found.append((float(item[1]), float(item[2])))
        elif tag == "pts":
            found.extend(_shape_points(item))
    return found


def _outline_mirror_axis(tree: list) -> float:
    """``ymin + ymax`` over the file's Edge.Cuts geometry (0.0 without one)."""
    ys = [y for _x, y in _outline_points(tree)]
    return (min(ys) + max(ys)) if ys else 0.0


def _flip_y(y: float, axis: float) -> float:
    """KiCad Y-down -> IR Y-up (involutive; rounded so round-trips are exact)."""
    return round(axis - y, 6) + 0.0  # + 0.0 normalizes -0.0


def _read_drill(pad: list, pad_type: str) -> Drill | None:
    """A pad's hole, or None for SMD.

    Dropping this was the importer's most expensive omission: every through-hole
    pad — every header, every DIP, every connector — came back as surface mount,
    so a round trip quietly produced a board with no holes in it.
    """
    node = _find(pad, "drill")
    if node is None:
        return None
    plated = pad_type != "np_thru_hole"
    rest = [x for x in node[1:] if not isinstance(x, list)]
    if rest and str(rest[0]) == "oval" and len(rest) >= 3:
        return Drill(oval=[float(rest[1]), float(rest[2])], plated=plated)
    if rest:
        return Drill(diameter=float(rest[0]), plated=plated)
    return None


class KiCadImporter(Importer):
    """Import a KiCad PCB into ForgeLab IR."""

    tool_name = "kicad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        try:
            tree = parse(source.decode("utf-8"))
        except SExprError as exc:
            raise KiCadParseError(str(exc)) from exc
        if not tree or tree[0] != "kicad_pcb":
            raise KiCadParseError("root element is not (kicad_pcb ...)")

        # KiCad is Y-down, the IR is Y-up: every absolute Y read below goes
        # through _flip_y about the outline's vertical centre.
        axis = _outline_mirror_axis(tree)
        board = self._read_board(tree, axis)
        nets = self._read_nets(tree)
        components = self._read_components(tree, axis)
        tracks = self._read_tracks(tree, axis)
        vias = self._read_vias(tree, axis)
        zones = self._read_zones(tree, axis)

        nodes: list[Node] = [Node(id=NODE_BOARD, type=NODE_BOARD, props=board.model_dump())]
        for net in sorted(nets, key=lambda n: n.code):
            nodes.append(Node(id=f"net:{net.code}", type=NODE_NET, props=net.model_dump()))
        for comp in components:
            nodes.append(Node(id=comp.reference, type=NODE_COMPONENT, props=comp.model_dump()))
        for i, track in enumerate(tracks, 1):
            nodes.append(Node(id=f"track_{i}", type=NODE_TRACK, props=track.model_dump()))
        for i, via in enumerate(vias, 1):
            nodes.append(Node(id=f"via_{i}", type=NODE_VIA, props=via.model_dump()))
        for i, zone in enumerate(zones, 1):
            nodes.append(Node(id=f"zone_{i}", type=NODE_ZONE, props=zone.model_dump()))

        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.HARDWARE,
            # The source file's name, not a hard-coded one: every imported board
            # used to come back called "blinky", whatever it actually was.
            meta=DocumentMeta(name=self.source_name or "board", generator="forgelab-kicad"),
            nodes=nodes,
        )

    def _read_board(self, tree: list, axis: float) -> BoardConstraints:
        version = str(_value(tree, "version", "20221018"))
        generator = str(_value(tree, "generator", "pcbnew"))

        layers: list[BoardLayer] = []
        layers_block = _find(tree, "layers")
        if layers_block is not None:
            for entry in layers_block[1:]:
                if isinstance(entry, list) and len(entry) >= 3:
                    layers.append(
                        BoardLayer(
                            ordinal=int(entry[0]),
                            canonical_name=str(entry[1]),
                            layer_type=str(entry[2]),
                            user_name=str(entry[3]) if len(entry) > 3 else None,
                        )
                    )

        # Design rules live in the Default net class (KiCad 6+ / our exporter);
        # fall back to legacy (setup ...) keys for older boards.
        net_class = next(
            (nc for nc in _find_all(tree, "net_class") if len(nc) > 1 and str(nc[1]) == "Default"),
            None,
        )
        setup = _find(tree, "setup") or []
        source = net_class if net_class is not None else setup
        rules = DesignRules(
            clearance=float(_value(source, "clearance", 0.2)),
            track_width=float(_value(source, "trace_width", 0.25)),
            via_diameter=float(_value(source, "via_dia", _value(source, "via_diameter", 0.8))),
            via_drill=float(_value(source, "via_drill", 0.4)),
        )

        outline = self._read_outline(tree, axis)

        return BoardConstraints(
            kicad_version=version,
            generator=generator,
            layers=layers,
            outline=outline,
            design_rules=rules,
        )

    def _read_outline(self, tree: list, axis: float) -> list[OutlineSegment]:
        """Edge.Cuts as line and arc segments.

        ``gr_rect`` becomes its four sides and ``gr_arc`` keeps its curvature via
        the segment's ``arc_mid`` — KiCad states an arc as start/mid/end and so
        does the IR, so the shape survives the trip rather than being flattened
        to a chord or dropped entirely.
        """

        def point(node: list | None) -> list[float] | None:
            if node is None or len(node) < 3:
                return None
            return [float(node[1]), _flip_y(float(node[2]), axis)]

        outline: list[OutlineSegment] = []
        for line in _find_all(tree, "gr_line"):
            if _value(line, "layer") != "Edge.Cuts":
                continue
            start, end = point(_find(line, "start")), point(_find(line, "end"))
            if start and end:
                outline.append(OutlineSegment(start=start, end=end))

        for arc in _find_all(tree, "gr_arc"):
            if _value(arc, "layer") != "Edge.Cuts":
                continue
            start, mid, end = (
                point(_find(arc, "start")),
                point(_find(arc, "mid")),
                point(_find(arc, "end")),
            )
            if start and end:
                outline.append(OutlineSegment(start=start, end=end, arc_mid=mid))

        for rect in _find_all(tree, "gr_rect"):
            if _value(rect, "layer") != "Edge.Cuts":
                continue
            start, end = point(_find(rect, "start")), point(_find(rect, "end"))
            if start and end:
                (x0, y0), (x1, y1) = (start[0], start[1]), (end[0], end[1])
                corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                outline.extend(
                    OutlineSegment(start=corners[i], end=corners[(i + 1) % 4]) for i in range(4)
                )
        return outline

    def _read_tracks(self, tree: list, axis: float) -> list[Track]:
        """``(segment ...)`` -> Track. The exporter has always written these; not
        reading them meant a round trip silently unrouted the board."""
        tracks: list[Track] = []
        for seg in _find_all(tree, "segment"):
            start, end = _find(seg, "start"), _find(seg, "end")
            if not (start and end and len(start) >= 3 and len(end) >= 3):
                continue
            net_node = _find(seg, "net")
            tracks.append(
                Track(
                    net=self._net_name(tree, net_node),
                    layer=str(_value(seg, "layer", "F.Cu")),
                    start=[float(start[1]), _flip_y(float(start[2]), axis)],
                    end=[float(end[1]), _flip_y(float(end[2]), axis)],
                    width=float(_value(seg, "width", 0.25)),
                )
            )
        return tracks

    def _read_vias(self, tree: list, axis: float) -> list[Via]:
        vias: list[Via] = []
        for via in _find_all(tree, "via"):
            at = _find(via, "at")
            if not (at and len(at) >= 3):
                continue
            vias.append(
                Via(
                    at=[float(at[1]), _flip_y(float(at[2]), axis)],
                    net=self._net_name(tree, _find(via, "net")),
                    size=float(_value(via, "size", 0.8)),
                    drill=float(_value(via, "drill", 0.4)),
                )
            )
        return vias

    def _read_zones(self, tree: list, axis: float) -> list[Zone]:
        """``(zone ...)`` -> Zone, keeping the pour's outline polygon."""
        zones: list[Zone] = []
        for zone in _find_all(tree, "zone"):
            polygon_node = _find(zone, "polygon")
            points: list[list[float]] = []
            if polygon_node is not None:
                pts = _find(polygon_node, "pts")
                for xy in _find_all(pts or [], "xy"):
                    if len(xy) >= 3:
                        points.append([float(xy[1]), _flip_y(float(xy[2]), axis)])
            if len(points) < 3:
                continue
            zones.append(
                Zone(
                    net=str(_value(zone, "net_name", "")),
                    layer=str(_value(zone, "layer", "F.Cu")),
                    polygon=points,
                    min_thickness=float(_value(zone, "min_thickness", 0.25)),
                )
            )
        return zones

    def _net_name(self, tree: list, net_node: list | None) -> str:
        """A track/via names its net by code; the board's net table has the name."""
        if net_node is None or len(net_node) < 2:
            return ""
        code = net_node[1]
        # (net 3 "LED_A") on a pad carries the name inline; (net 3) on a segment
        # does not, so fall back to the board-level table.
        if len(net_node) >= 3:
            return str(net_node[2])
        for net in _find_all(tree, "net"):
            if len(net) >= 3 and net[1] == code:
                return str(net[2])
        return ""

    def _read_nets(self, tree: list) -> list[Net]:
        nets: list[Net] = []
        for net in _find_all(tree, "net"):
            if len(net) >= 3:
                nets.append(Net(code=int(net[1]), name=str(net[2])))
            elif len(net) == 2:
                nets.append(Net(code=int(net[1]), name=""))
        return nets

    def _read_components(self, tree: list, axis: float) -> list[Component]:
        components: list[Component] = []
        for fp in _find_all(tree, "footprint"):
            footprint_id = str(fp[1]) if len(fp) > 1 else ""
            layer = str(_value(fp, "layer", "F.Cu"))
            uuid = _value(fp, "uuid")
            at_node = _find(fp, "at")
            at = _floats(at_node[1:4]) if at_node else [0.0, 0.0, 0.0]
            if len(at) == 2:
                at = [at[0], at[1], 0.0]
            # Absolute Y into the IR's Y-up frame; rotation passes through.
            at = [at[0], _flip_y(at[1], axis), at[2]]

            reference = ""
            value = ""
            for prop in _find_all(fp, "property"):
                if len(prop) >= 3 and prop[1] == "Reference":
                    reference = str(prop[2])
                elif len(prop) >= 3 and prop[1] == "Value":
                    value = str(prop[2])

            pads: list[Pad] = []
            for pad in _find_all(fp, "pad"):
                number = str(pad[1]) if len(pad) > 1 else ""
                net_node = _find(pad, "net")
                net_name = str(net_node[2]) if net_node and len(net_node) >= 3 else ""
                at_node = _find(pad, "at")
                pad_at = _floats(at_node[1:3]) if at_node and len(at_node) >= 3 else None
                if pad_at is not None:
                    # Pad-local offsets: negate into the Y-up footprint frame.
                    pad_at = [pad_at[0], -pad_at[1] + 0.0]
                size_node = _find(pad, "size")
                pad_size = _floats(size_node[1:3]) if size_node and len(size_node) >= 3 else None
                # (pad "1" smd roundrect ...) — type at [2], shape at [3].
                pad_type = str(pad[2]) if len(pad) > 2 and not isinstance(pad[2], list) else "smd"
                shape = str(pad[3]) if len(pad) > 3 and not isinstance(pad[3], list) else None
                pads.append(
                    Pad(
                        number=number,
                        net=net_name,
                        at=pad_at,
                        size=pad_size,
                        shape=shape,
                        drill=_read_drill(pad, pad_type),
                    )
                )

            components.append(
                Component(
                    reference=reference,
                    value=value,
                    footprint=footprint_id,
                    layer=layer,
                    at=at,
                    pads=pads,
                    uuid=str(uuid) if uuid is not None else None,
                )
            )
        return components
