"""Electrical rule checking: is this board actually wired the way it says?

Everything else that checks a hardware document measures *geometry* — how far
apart the copper is, whether a pad overlaps another pad, whether a part fits on
the board. None of it asks the question a schematic review asks first: does the
copper connect the things the netlist says are connected?

It did not, and the gap was wide enough to drive a board through. A design where
a third of the nets failed to route still reported ``passed: True``, because
every geometric rule was satisfied — there simply was no copper where the
connection should have been. KiCad calls that ``unconnected_items`` and treats it
as an error; ForgeLab had nothing to say about it at all.

What connectivity means here: pads, tracks and vias are joined into groups by
touching. Two pieces of copper touch when they share a layer and their shapes
meet — a through-hole pad or a via touches on every layer, an SMD pad only on
its own. A net is *routed* when all of its pads land in one group.

The model works from the same resolved pad geometry the exporters draw, so what
it measures is the copper that will actually be manufactured.

**Where it stops.** Copper pours are treated as connecting every same-net pad
whose centre falls inside them on that layer. That is an approximation: KiCad
computes a real fill, with clearances, thermal reliefs and island removal, and a
pad inside the outline is not always reached by the copper. ForgeLab does not
reimplement that fill (see ``forgelab.spec.hardware.Zone``), so on a poured net
this check can say "connected" where KiCad would not.

Checked against ``kicad-cli`` on the routed Arduino Uno, it agrees on 7 of the 8
nets KiCad reports and raises **no false alarms** — the miss is exactly the
poured net. So: a net this reports as unrouted really is unrouted, and a poured
net's last word belongs to ``verify_geometry``, which runs KiCad's own DRC.
"""

from __future__ import annotations

import math
from typing import Any

from forgelab.footprints import resolve as resolve_pads
from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.hardware import (
    NODE_COMPONENT,
    NODE_NET,
    NODE_TRACK,
    NODE_VIA,
    NODE_ZONE,
)

#: Copper this close together is treated as touching. Tracks are generated on a
#: grid and their endpoints land on pad centres, so exact equality is too strict
#: for floating-point coordinates while anything larger would invent contacts.
_TOUCH_EPSILON = 1e-6


class _Union:
    """Disjoint-set over copper pieces, so "is this net one island?" is a lookup."""

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def add(self, item: int) -> None:
        self._parent.setdefault(item, item)

    def find(self, item: int) -> int:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _rect(cx: float, cy: float, w: float, h: float) -> tuple[float, float, float, float]:
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _rects_touch(a: tuple, b: tuple) -> bool:
    return (
        a[0] <= b[2] + _TOUCH_EPSILON
        and b[0] <= a[2] + _TOUCH_EPSILON
        and a[1] <= b[3] + _TOUCH_EPSILON
        and b[1] <= a[3] + _TOUCH_EPSILON
    )


def _segment_touches_rect(p0: tuple, p1: tuple, rect: tuple, width: float) -> bool:
    """Whether a track of ``width`` from p0 to p1 reaches into ``rect``."""
    grown = (
        rect[0] - width / 2,
        rect[1] - width / 2,
        rect[2] + width / 2,
        rect[3] + width / 2,
    )
    # Cheap and sufficient: the router lays copper orthogonally and ends runs on
    # pad centres, so an endpoint inside the pad is the real contact case.
    for px, py in (p0, p1):
        if grown[0] <= px <= grown[2] and grown[1] <= py <= grown[3]:
            return True
    return _rects_touch(
        (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1])),
        grown,
    ) and _segment_crosses(p0, p1, grown)


def _segment_crosses(p0: tuple, p1: tuple, rect: tuple) -> bool:
    """Liang-Barsky: does the segment intersect the axis-aligned rectangle?"""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, p0[0] - rect[0]),
        (dx, rect[2] - p0[0]),
        (-dy, p0[1] - rect[1]),
        (dy, rect[3] - p0[1]),
    ):
        if abs(p) < _TOUCH_EPSILON:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _point_in_polygon(x: float, y: float, polygon: list) -> bool:
    inside = False
    count = len(polygon)
    for i in range(count):
        x0, y0 = float(polygon[i][0]), float(polygon[i][1])
        x1, y1 = float(polygon[(i + 1) % count][0]), float(polygon[(i + 1) % count][1])
        if (y0 > y) != (y1 > y):
            cross = x0 + (y - y0) / (y1 - y0) * (x1 - x0)
            if x < cross:
                inside = not inside
    return inside


class _Copper:
    """One piece of copper: where it is, what layer(s), and which net claims it."""

    __slots__ = ("index", "net", "layers", "rect", "p0", "p1", "width", "kind", "label")

    def __init__(
        self,
        index: int,
        net: str,
        layers: set[str],
        rect: tuple,
        kind: str,
        label: str,
        p0: tuple | None = None,
        p1: tuple | None = None,
        width: float = 0.0,
    ) -> None:
        self.index = index
        self.net = net
        self.layers = layers
        self.rect = rect
        self.kind = kind
        self.label = label
        self.p0 = p0
        self.p1 = p1
        self.width = width


_ALL_COPPER = {"*"}


def _shares_layer(a: set[str], b: set[str]) -> bool:
    return bool(a & b) or bool(_ALL_COPPER & a) or bool(_ALL_COPPER & b)


def _collect(document: ForgeDocument) -> tuple[list[_Copper], list[dict]]:
    """Every piece of copper on the board, plus the copper pours."""
    pieces: list[_Copper] = []
    zones: list[dict] = []
    for node in document.walk():
        props = node.props
        if node.type == NODE_COMPONENT:
            at = props.get("at") or [0.0, 0.0]
            if not (isinstance(at, list) and len(at) >= 2):
                continue
            cx, cy = float(at[0]), float(at[1])
            rotation = float(at[2]) if len(at) >= 3 else 0.0
            side = str(props.get("layer") or "F.Cu")
            ref = str(props.get("reference") or node.id)
            for pad in resolve_pads(props.get("footprint"), props.get("pads") or []):
                theta = math.radians(rotation)
                rx = pad.x * math.cos(theta) - pad.y * math.sin(theta)
                ry = pad.x * math.sin(theta) + pad.y * math.cos(theta)
                hw, hh = pad.rotated_half_extents(rotation)
                pieces.append(
                    _Copper(
                        index=len(pieces),
                        net=pad.net,
                        layers=_ALL_COPPER if pad.through_hole else {side},
                        rect=(cx + rx - hw, cy + ry - hh, cx + rx + hw, cy + ry + hh),
                        kind="pad",
                        label=f"pad {pad.number or '?'} of {ref}",
                    )
                )
        elif node.type == NODE_TRACK:
            start, end = props.get("start"), props.get("end")
            if not (isinstance(start, list) and isinstance(end, list)):
                continue
            p0 = (float(start[0]), float(start[1]))
            p1 = (float(end[0]), float(end[1]))
            width = float(props.get("width") or 0.25)
            pieces.append(
                _Copper(
                    index=len(pieces),
                    net=str(props.get("net", "")),
                    layers={str(props.get("layer") or "F.Cu")},
                    rect=(
                        min(p0[0], p1[0]) - width / 2,
                        min(p0[1], p1[1]) - width / 2,
                        max(p0[0], p1[0]) + width / 2,
                        max(p0[1], p1[1]) + width / 2,
                    ),
                    kind="track",
                    label="track",
                    p0=p0,
                    p1=p1,
                    width=width,
                )
            )
        elif node.type == NODE_VIA:
            at = props.get("at")
            if not (isinstance(at, list) and len(at) >= 2):
                continue
            size = float(props.get("size") or 0.8)
            pieces.append(
                _Copper(
                    index=len(pieces),
                    net=str(props.get("net", "")),
                    layers=_ALL_COPPER,
                    rect=_rect(float(at[0]), float(at[1]), size, size),
                    kind="via",
                    label="via",
                )
            )
        elif node.type == NODE_ZONE:
            polygon = props.get("polygon")
            if isinstance(polygon, list) and len(polygon) >= 3:
                zones.append(
                    {
                        "net": str(props.get("net", "")),
                        "layer": str(props.get("layer") or "F.Cu"),
                        "polygon": polygon,
                    }
                )
    return pieces, zones


def _touching(a: _Copper, b: _Copper) -> bool:
    if not _shares_layer(a.layers, b.layers):
        return False
    # A track is a line with width; everything else is a rectangle. Only the
    # track carries endpoints, which is what the kind check below establishes.
    if a.kind == "track" and b.kind != "track" and a.p0 and a.p1:
        return _segment_touches_rect(a.p0, a.p1, b.rect, a.width)
    if b.kind == "track" and a.kind != "track" and b.p0 and b.p1:
        return _segment_touches_rect(b.p0, b.p1, a.rect, b.width)
    return _rects_touch(a.rect, b.rect)


def check_connectivity(document: ForgeDocument) -> list[str]:
    """Nets whose pads are not all joined by copper.

    One message per unrouted net, naming how many islands its pads fall into,
    because that is what tells the caller whether it is one missing track or a
    net that was never routed at all.
    """
    pieces, zones = _collect(document)
    groups = _Union()
    for piece in pieces:
        groups.add(piece.index)

    # Same-net copper that physically touches is one island.
    for i, a in enumerate(pieces):
        if not a.net:
            continue
        for b in pieces[i + 1 :]:
            if a.net == b.net and _touching(a, b):
                groups.union(a.index, b.index)

    # A pour joins every pad of its own net that sits inside it.
    for zone in zones:
        inside = [
            p
            for p in pieces
            if p.net == zone["net"]
            and _shares_layer(p.layers, {zone["layer"]})
            and _point_in_polygon(
                (p.rect[0] + p.rect[2]) / 2, (p.rect[1] + p.rect[3]) / 2, zone["polygon"]
            )
        ]
        for other in inside[1:]:
            groups.union(inside[0].index, other.index)

    by_net: dict[str, list[_Copper]] = {}
    for piece in pieces:
        if piece.kind == "pad" and piece.net:
            by_net.setdefault(piece.net, []).append(piece)

    errors: list[str] = []
    for net, pads in sorted(by_net.items()):
        if len(pads) < 2:
            continue
        islands = {groups.find(p.index) for p in pads}
        if len(islands) > 1:
            names = ", ".join(sorted(p.label for p in pads)[:4])
            more = "" if len(pads) <= 4 else f" (+{len(pads) - 4} more)"
            errors.append(
                f"Net {net} is not fully routed — its {len(pads)} pads fall into "
                f"{len(islands)} unconnected groups: {names}{more}. Run route_board."
            )
    return errors


def check_electrical(document: ForgeDocument) -> tuple[list[str], list[str]]:
    """``(errors, warnings)`` for a hardware document's netlist.

    Connectivity is reported as a **warning**, not an error, and deliberately: a
    board that has been generated but not yet routed is a normal step in the
    workflow, not a broken document, and `validate_document` runs throughout
    authoring. Where the question is instead "can this be manufactured", the
    answer has to be no — `check_gerber_completeness` raises the same finding to
    an error, because a Gerber set with a missing connection is a dead board.
    """
    if document.domain != Domain.HARDWARE:
        return [], []

    errors: list[str] = []
    warnings: list[str] = []
    nodes = list(document.walk())
    components = [n for n in nodes if n.type == NODE_COMPONENT]
    nets = [n for n in nodes if n.type == NODE_NET]

    # Duplicate reference designators: two parts the BOM and the netlist cannot
    # tell apart, and which KiCad will refuse to load as separate footprints.
    seen: dict[str, int] = {}
    for comp in components:
        ref = str(comp.props.get("reference") or comp.id)
        seen[ref] = seen.get(ref, 0) + 1
    for ref, count in sorted(seen.items()):
        if count > 1:
            errors.append(f"Reference designator {ref} is used by {count} components")

    # Duplicate net codes: the exporter writes the code, so two nets sharing one
    # silently merge into a single net in the board file.
    codes: dict[Any, list[str]] = {}
    for net in nets:
        codes.setdefault(net.props.get("code"), []).append(str(net.props.get("name", "")))
    for code, names in sorted(codes.items(), key=lambda kv: str(kv[0])):
        if len(names) > 1:
            errors.append(
                f"Net code {code} is claimed by {len(names)} nets ({', '.join(sorted(names))}) "
                "— they would merge into one net on export"
            )

    # A net with exactly one pad connects nothing; a net with none is dead
    # weight. Both are warnings: they are usually a half-finished design rather
    # than a mistake, and neither makes the board unbuildable.
    pads_per_net: dict[str, int] = {}
    for comp in components:
        for pad in comp.props.get("pads") or []:
            if isinstance(pad, dict) and pad.get("net"):
                name = str(pad["net"])
                pads_per_net[name] = pads_per_net.get(name, 0) + 1
    for net in nets:
        name = str(net.props.get("name", ""))
        if not name:
            continue
        count = pads_per_net.get(name, 0)
        if count == 0:
            warnings.append(f"Net {name} has no pads on it")
        elif count == 1:
            warnings.append(f"Net {name} reaches only one pad, so it connects nothing")

    # Layers referenced but never declared.
    declared = {
        str(layer.get("canonical_name"))
        for node in nodes
        if node.type == "board"
        for layer in node.props.get("layers") or []
        if isinstance(layer, dict)
    }
    if declared:
        for node in nodes:
            if node.type not in (NODE_COMPONENT, NODE_TRACK, NODE_ZONE):
                continue
            layer = str(node.props.get("layer") or "")
            if layer and layer not in declared:
                errors.append(
                    f"{node.id} is on layer {layer!r}, which the board does not declare "
                    f"(declared: {', '.join(sorted(declared))})"
                )

    warnings.extend(check_connectivity(document))
    return errors, warnings
