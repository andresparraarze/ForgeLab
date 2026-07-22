"""Fabrication rule checks: validate a hardware design against a PCB fab's limits.

Before a board goes out for manufacture it must respect the fab's minimum trace
width, via geometry, and board-size envelope. This module encodes named profiles
for common budget fabs and checks a hardware document's ``design_rules`` and board
outline against the chosen profile.

Returned ``errors`` are hard rule violations (the fab would reject or panelize
the board); ``warnings`` flag things that could not be checked (e.g. no outline to
measure). Pure standard library; node payloads are read as plain dicts.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

from forgelab.layout import component_rotation, rotate_offset
from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.hardware import (
    DEFAULT_ZONE_MIN_THICKNESS,
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_TRACK,
    NODE_VIA,
    NODE_ZONE,
    pad_default_size,
    pad_grid_offset,
)

# Floating-point slack so an exactly-at-minimum value (0.1 vs 0.1) passes.
_EPS = 1e-9

# Named fab profiles. Only the keys present are checked, so a profile without
# board-size limits (e.g. OSH Park) simply skips that check.
_FAB_PROFILES: dict[str, dict[str, float]] = {
    "jlcpcb": {
        "min_trace_width": 0.1,
        "min_trace_spacing": 0.1,
        "min_via_diameter": 0.45,
        "min_via_drill": 0.2,
        "min_drill_size": 0.2,
        "max_board_width": 500.0,
        "max_board_height": 500.0,
        "min_board_width": 5.0,
        "min_board_height": 5.0,
        "min_silkscreen_text_height": 0.8,
    },
    "pcbway": {
        "min_trace_width": 0.1,
        "min_trace_spacing": 0.1,
        "min_via_diameter": 0.45,
        "min_via_drill": 0.2,
        "min_drill_size": 0.2,
        "max_board_width": 600.0,
        "max_board_height": 600.0,
        "min_board_width": 5.0,
        "min_board_height": 5.0,
    },
    "oshpark": {
        "min_trace_width": 0.1,
        "min_trace_spacing": 0.1,
        "min_via_diameter": 0.406,
        "min_via_drill": 0.203,
    },
}

DEFAULT_FAB = "jlcpcb"


def fab_profile_names() -> list[str]:
    """The names of the available fab profiles."""
    return list(_FAB_PROFILES)


def fab_profiles() -> dict[str, dict[str, float]]:
    """All fab profiles, name -> constraint table (a copy per profile)."""
    return {name: dict(rules) for name, rules in _FAB_PROFILES.items()}


def _below(value: float, minimum: float) -> bool:
    return value < minimum - _EPS


def _above(value: float, maximum: float) -> bool:
    return value > maximum + _EPS


def _board_node(document: ForgeDocument) -> Any:
    for node in document.walk():
        if node.type == NODE_BOARD:
            return node
    return None


def _outline_bounds(outline: Any) -> tuple[float, float] | None:
    """Bounding-box (width, height) over an outline's segment endpoints, or None."""
    if not isinstance(outline, list) or not outline:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for seg in outline:
        if not isinstance(seg, dict):
            continue
        for key in ("start", "end"):
            point = seg.get(key)
            if isinstance(point, list) and len(point) == 2:
                try:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
                except (TypeError, ValueError):
                    return None
    if not xs or not ys:
        return None
    return max(xs) - min(xs), max(ys) - min(ys)


def _segment_distance(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> float:
    """Minimum distance between two 2D line segments."""

    def point_seg(p: tuple[float, float], s1: tuple[float, float], s2: tuple[float, float]):
        dx, dy = s2[0] - s1[0], s2[1] - s1[1]
        length2 = dx * dx + dy * dy
        if length2 == 0:
            return math.dist(p, s1)
        t = max(0.0, min(1.0, ((p[0] - s1[0]) * dx + (p[1] - s1[1]) * dy) / length2))
        return math.dist(p, (s1[0] + t * dx, s1[1] + t * dy))

    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    # Proper intersection -> distance zero.
    d1, d2 = orient(b1, b2, a1), orient(b1, b2, a2)
    d3, d4 = orient(a1, a2, b1), orient(a1, a2, b2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(
        point_seg(a1, b1, b2),
        point_seg(a2, b1, b2),
        point_seg(b1, a1, a2),
        point_seg(b2, a1, a2),
    )


def _check_routed_copper(
    document: ForgeDocument, fab: str, profile: dict[str, float], errors: list[str]
) -> None:
    """Validate actually-routed tracks and vias, not just declared design rules."""
    tracks: list[dict[str, Any]] = []
    for node in document.walk():
        if node.type == NODE_TRACK:
            props = node.props
            width = float(props.get("width", 0.0))
            if _below(width, profile["min_trace_width"]):
                errors.append(
                    f"routed track on net {props.get('net', '?')} has width {width}mm, "
                    f"below {fab} minimum trace width {profile['min_trace_width']}mm"
                )
            tracks.append(props)
        elif node.type == NODE_VIA:
            size = float(node.props.get("size", 0.0))
            drill = float(node.props.get("drill", 0.0))
            if _below(size, profile["min_via_diameter"]):
                errors.append(
                    f"routed via on net {node.props.get('net', '?')} has size {size}mm, "
                    f"below {fab} minimum via diameter {profile['min_via_diameter']}mm"
                )
            if _below(drill, profile["min_via_drill"]):
                errors.append(
                    f"routed via on net {node.props.get('net', '?')} has drill {drill}mm, "
                    f"below {fab} minimum via drill {profile['min_via_drill']}mm"
                )

    # Copper-to-copper clearance between tracks of different nets on the same
    # layer: edge-to-edge gap = centreline distance minus half of each width.
    min_spacing = profile.get("min_trace_spacing")
    if min_spacing is None:
        return
    reported: set[tuple[str, str]] = set()
    for i, a in enumerate(tracks):
        for b in tracks[i + 1 :]:
            if a.get("layer") != b.get("layer") or a.get("net") == b.get("net"):
                continue
            pair = tuple(sorted((str(a.get("net")), str(b.get("net")))))
            if pair in reported:
                continue
            gap = (
                _segment_distance(
                    (float(a["start"][0]), float(a["start"][1])),
                    (float(a["end"][0]), float(a["end"][1])),
                    (float(b["start"][0]), float(b["start"][1])),
                    (float(b["end"][0]), float(b["end"][1])),
                )
                - (float(a.get("width", 0.0)) + float(b.get("width", 0.0))) / 2
            )
            if _below(gap, min_spacing):
                reported.add(pair)  # type: ignore[arg-type]
                errors.append(
                    f"routed tracks on nets {pair[0]} and {pair[1]} ({a.get('layer')}) are "
                    f"{max(gap, 0.0):.3f}mm apart, below {fab} minimum clearance {min_spacing}mm"
                )


class _PadCopper(NamedTuple):
    """A pad's absolute copper geometry, resolved from its component."""

    ref: str
    number: str
    net: str
    layer: str
    cx: float
    cy: float
    width: float
    height: float
    rotation: float
    circle: bool


def _collect_pad_copper(document: ForgeDocument) -> list[_PadCopper]:
    """Every pad's absolute copper rectangle/circle, exactly as exported.

    Size-less pads use the shared pitch-aware default and ``at``-less pads
    the deterministic fallback grid (both from ``forgelab.spec.hardware``),
    so these checks measure the same copper the KiCad and Gerber exporters
    render.
    """
    out: list[_PadCopper] = []
    for node in document.walk():
        if node.type != NODE_COMPONENT:
            continue
        props = node.props
        at = props.get("at") or [0.0, 0.0]
        if not (isinstance(at, list) and len(at) >= 2):
            continue
        cx, cy = float(at[0]), float(at[1])
        rotation = component_rotation(props)
        layer = str(props.get("layer") or "F.Cu")
        ref = str(props.get("reference") or node.id)
        pads = [p for p in props.get("pads") or [] if isinstance(p, dict)]
        default = pad_default_size([p.get("at") for p in pads])
        for index, pad in enumerate(pads):
            offset = pad.get("at")
            if isinstance(offset, list) and len(offset) == 2:
                ox, oy = float(offset[0]), float(offset[1])
            else:
                ox, oy = pad_grid_offset(index, len(pads))
            rx, ry = rotate_offset(ox, oy, rotation)
            size = pad.get("size")
            if isinstance(size, list) and len(size) == 2:
                width, height = float(size[0]), float(size[1])
            else:
                width = height = default
            out.append(
                _PadCopper(
                    ref=ref,
                    number=str(pad.get("number", "?")),
                    net=str(pad.get("net", "")),
                    layer=layer,
                    cx=cx + rx,
                    cy=cy + ry,
                    width=width,
                    height=height,
                    rotation=rotation,
                    circle=str(pad.get("shape") or "") == "circle",
                )
            )
    return out


def _point_pad_gap(px: float, py: float, pad: _PadCopper) -> float:
    """Distance from a point to the pad's copper edge (0 inside the copper)."""
    if pad.circle:
        return max(0.0, math.dist((px, py), (pad.cx, pad.cy)) - pad.width / 2)
    # Rotate the point into the pad's frame, then clamp against the rectangle.
    dx, dy = px - pad.cx, py - pad.cy
    theta = math.radians(pad.rotation)
    cos_r, sin_r = math.cos(theta), math.sin(theta)
    local_x = dx * cos_r + dy * sin_r
    local_y = -dx * sin_r + dy * cos_r
    return math.hypot(
        max(abs(local_x) - pad.width / 2, 0.0), max(abs(local_y) - pad.height / 2, 0.0)
    )


def _pad_corners(pad: _PadCopper) -> list[tuple[float, float]]:
    theta = math.radians(pad.rotation)
    cos_r, sin_r = math.cos(theta), math.sin(theta)
    hw, hh = pad.width / 2, pad.height / 2
    return [
        (pad.cx + x * cos_r - y * sin_r, pad.cy + x * sin_r + y * cos_r)
        for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))
    ]


def _pad_pad_gap(a: _PadCopper, b: _PadCopper) -> float:
    """Edge-to-edge copper gap between two pads (0 when they overlap)."""
    if a.circle:
        return max(0.0, _point_pad_gap(a.cx, a.cy, b) - a.width / 2)
    if b.circle:
        return max(0.0, _point_pad_gap(b.cx, b.cy, a) - b.width / 2)
    # Overlap: crossing edges hit the segment-distance intersection test; one
    # rect swallowing the other is caught by the centre-containment probes.
    if _point_pad_gap(a.cx, a.cy, b) == 0.0 or _point_pad_gap(b.cx, b.cy, a) == 0.0:
        return 0.0
    edges_a, edges_b = _pad_corners(a), _pad_corners(b)
    return min(
        _segment_distance(edges_a[i], edges_a[(i + 1) % 4], edges_b[j], edges_b[(j + 1) % 4])
        for i in range(4)
        for j in range(4)
    )


def _segment_pad_gap(s1: tuple[float, float], s2: tuple[float, float], pad: _PadCopper) -> float:
    """Gap between a track centreline segment and the pad's copper edge."""
    if pad.circle:
        centre = (pad.cx, pad.cy)
        return max(0.0, _segment_distance(s1, s2, centre, centre) - pad.width / 2)
    if _point_pad_gap(*s1, pad) == 0.0 or _point_pad_gap(*s2, pad) == 0.0:
        return 0.0
    corners = _pad_corners(pad)
    return min(_segment_distance(s1, s2, corners[i], corners[(i + 1) % 4]) for i in range(4))


def _check_copper_collisions(
    document: ForgeDocument, fab: str, profile: dict[str, float], errors: list[str]
) -> None:
    """Clearance between distinct copper items, the checks DRC actually runs.

    Covers via-to-pad, via-to-via, pad-to-pad, track-to-pad and track-to-via
    gaps across nets — the geometry whose absence let ``passed: true`` boards
    carry real short circuits (KiCad DRC on a routed board found vias landing
    on foreign pads and via pairs 0.1mm apart). Same-net contact is legal
    copper and never reported; a pad with no net counts as foreign to every
    net. Each check reports one message per offending net pair.
    """
    min_spacing = profile.get("min_trace_spacing")
    if min_spacing is None:
        return

    pads = _collect_pad_copper(document)
    vias: list[tuple[str, float, float, float]] = []
    tracks: list[tuple[str, str, tuple[float, float], tuple[float, float], float]] = []
    for node in document.walk():
        if node.type == NODE_VIA:
            at = node.props.get("at")
            if isinstance(at, list) and len(at) == 2:
                vias.append(
                    (
                        str(node.props.get("net", "")),
                        float(at[0]),
                        float(at[1]),
                        float(node.props.get("size", 0.0)),
                    )
                )
        elif node.type == NODE_TRACK:
            start, end = node.props.get("start"), node.props.get("end")
            if isinstance(start, list) and isinstance(end, list):
                tracks.append(
                    (
                        str(node.props.get("net", "")),
                        str(node.props.get("layer", "F.Cu")),
                        (float(start[0]), float(start[1])),
                        (float(end[0]), float(end[1])),
                        float(node.props.get("width", 0.0)),
                    )
                )

    reported: set[tuple[str, str, str]] = set()

    def report(kind: str, net_a: str, net_b: str, gap: float, what: str, remedy: str) -> None:
        pair = tuple(sorted((net_a or "?", net_b or "unconnected")))
        key = (kind, pair[0], pair[1])
        if key in reported:
            return
        reported.add(key)
        state = (
            "overlap — a short circuit"
            if gap <= 0
            else f"are {gap:.3f}mm apart, below {fab} minimum clearance {min_spacing}mm"
        )
        errors.append(f"{what} {state}; {remedy}")

    reroute = "re-run route_board to regenerate legal copper"
    for via_net, vx, vy, via_size in vias:
        for pad in pads:
            if pad.net and pad.net == via_net:
                continue
            gap = _point_pad_gap(vx, vy, pad) - via_size / 2
            if _below(gap, min_spacing):
                report(
                    "via-pad",
                    via_net,
                    pad.net,
                    gap,
                    f"routed via on net {via_net or '?'} at ({vx:g}, {vy:g}) and pad "
                    f"{pad.number} of {pad.ref} (net {pad.net or 'unconnected'})",
                    reroute,
                )
    for i, (net_a, ax, ay, size_a) in enumerate(vias):
        for net_b, bx, by, size_b in vias[i + 1 :]:
            if net_a == net_b:
                continue
            gap = math.dist((ax, ay), (bx, by)) - (size_a + size_b) / 2
            if _below(gap, min_spacing):
                report(
                    "via-via",
                    net_a,
                    net_b,
                    gap,
                    f"routed vias on nets {net_a or '?'} and {net_b or '?'} at "
                    f"({ax:g}, {ay:g}) and ({bx:g}, {by:g})",
                    reroute,
                )
    for i, pad_a in enumerate(pads):
        for pad_b in pads[i + 1 :]:
            if (
                pad_a.layer != pad_b.layer
                or not pad_a.net
                or not pad_b.net
                or pad_a.net == pad_b.net
            ):
                continue
            gap = _pad_pad_gap(pad_a, pad_b)
            if _below(gap, min_spacing):
                remedy = (
                    "the footprint's own pads violate spacing — check the pad geometry"
                    if pad_a.ref == pad_b.ref
                    else "move the components apart (run auto_place to fix automatically)"
                )
                report(
                    "pad-pad",
                    pad_a.net,
                    pad_b.net,
                    gap,
                    f"pad {pad_a.number} of {pad_a.ref} (net {pad_a.net}) and pad "
                    f"{pad_b.number} of {pad_b.ref} (net {pad_b.net})",
                    remedy,
                )
    for track_net, track_layer, start, end, width in tracks:
        for pad in pads:
            if pad.layer != track_layer or (pad.net and pad.net == track_net):
                continue
            gap = _segment_pad_gap(start, end, pad) - width / 2
            if _below(gap, min_spacing):
                report(
                    "track-pad",
                    track_net,
                    pad.net,
                    gap,
                    f"routed track on net {track_net or '?'} and pad {pad.number} of "
                    f"{pad.ref} (net {pad.net or 'unconnected'})",
                    reroute,
                )
        for via_net, vx, vy, via_size in vias:
            if via_net == track_net:
                continue
            gap = _segment_distance(start, end, (vx, vy), (vx, vy)) - width / 2 - via_size / 2
            if _below(gap, min_spacing):
                report(
                    "track-via",
                    track_net,
                    via_net,
                    gap,
                    f"routed track on net {track_net or '?'} and via on net "
                    f"{via_net or '?'} at ({vx:g}, {vy:g})",
                    reroute,
                )


Point = tuple[float, float]


def _point_in_polygon(px: float, py: float, poly: list[Point]) -> bool:
    """Ray-casting point-in-polygon test (points on the edge count as inside)."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            x_cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < x_cross:
                inside = not inside
    return inside


def _point_polygon_boundary_gap(px: float, py: float, poly: list[Point]) -> float:
    """Distance from a point to the nearest polygon boundary edge."""
    n = len(poly)
    return min(_segment_distance((px, py), (px, py), poly[i], poly[(i + 1) % n]) for i in range(n))


def _polygons_overlap(a: list[Point], b: list[Point]) -> bool:
    """True if two polygons share interior area (edges cross or one contains the other)."""
    na, nb = len(a), len(b)
    for i in range(na):
        for j in range(nb):
            if (
                _segment_distance(a[i], a[(i + 1) % na], b[j], b[(j + 1) % nb]) == 0.0
            ):  # edges touch or cross
                return True
    # No edge intersection: one polygon is wholly inside the other (or disjoint).
    return _point_in_polygon(a[0][0], a[0][1], b) or _point_in_polygon(b[0][0], b[0][1], a)


class _ZoneCopper(NamedTuple):
    net: str
    layer: str
    clearance: float
    min_thickness: float
    poly: list[Point]


def _collect_zones(document: ForgeDocument, default_clearance: float) -> list[_ZoneCopper]:
    """Every zone's boundary and resolved parameters, skipping malformed ones."""
    out: list[_ZoneCopper] = []
    for node in document.walk():
        if node.type != NODE_ZONE:
            continue
        raw = node.props.get("polygon")
        if not isinstance(raw, list) or len(raw) < 3:
            continue
        poly = [(float(p[0]), float(p[1])) for p in raw if isinstance(p, list) and len(p) == 2]
        if len(poly) < 3:
            continue
        clr = node.props.get("clearance")
        out.append(
            _ZoneCopper(
                net=str(node.props.get("net", "")),
                layer=str(node.props.get("layer", "F.Cu")),
                clearance=float(clr) if clr is not None else default_clearance,
                min_thickness=float(node.props.get("min_thickness", DEFAULT_ZONE_MIN_THICKNESS)),
                poly=poly,
            )
        )
    return out


def _check_zone_clearance(
    document: ForgeDocument,
    fab: str,
    profile: dict[str, float],
    errors: list[str],
    default_clearance: float,
) -> None:
    """Validate copper pours conservatively against the fab's spacing rules.

    ForgeLab emits *unfilled* zone boundaries and lets KiCad compute the actual
    poured copper, so these checks work on the boundary polygon and the pour's
    declared parameters, not on the KiCad-computed fill (which the kicad-cli DRC
    test verifies). The model is deliberately conservative — it may warn about a
    boundary segment the fill never reaches, but it never silently misses a real
    short:

    * ``clearance`` below the fab's minimum spacing — the pour would be
      fabricated too close to the copper it surrounds;
    * ``min_thickness`` below the fab's minimum trace width — unmanufacturable
      copper slivers;
    * two same-layer, different-net pours whose boundaries overlap;
    * a foreign-net track/pad/via that lies **outside** a pour but within the
      fab's minimum spacing of its boundary (copper *inside* the boundary is not
      flagged — KiCad pours around it using the zone clearance checked above).
    """
    min_spacing = profile.get("min_trace_spacing")
    min_width = profile.get("min_trace_width")
    zones = _collect_zones(document, default_clearance)
    if not zones:
        return

    for zone in zones:
        if min_spacing is not None and _below(zone.clearance, min_spacing):
            errors.append(
                f"zone on net {zone.net or '?'} ({zone.layer}) has clearance "
                f"{zone.clearance}mm, below {fab} minimum clearance {min_spacing}mm"
            )
        if min_width is not None and _below(zone.min_thickness, min_width):
            errors.append(
                f"zone on net {zone.net or '?'} ({zone.layer}) has min_thickness "
                f"{zone.min_thickness}mm, below {fab} minimum trace width {min_width}mm"
            )

    # Two full pours of different nets on the same layer will fight for copper.
    for i, a in enumerate(zones):
        for b in zones[i + 1 :]:
            if a.layer == b.layer and a.net != b.net and _polygons_overlap(a.poly, b.poly):
                errors.append(
                    f"zones on nets {a.net or '?'} and {b.net or '?'} overlap on {a.layer} — "
                    "two different-net copper pours cannot share the same area"
                )

    if min_spacing is None:
        return

    # Foreign copper just outside a pour boundary: the fill reaches the boundary
    # and would be manufactured within clearance of it. Copper inside the
    # boundary is intentionally poured around, so it is not flagged here.
    pads = _collect_pad_copper(document)
    reported: set[tuple[str, str, str]] = set()

    def report_edge(net_a: str, net_b: str, what: str) -> None:
        key = tuple(sorted((net_a or "?", net_b or "unconnected")))
        full = ("edge", key[0], key[1])
        if full in reported:
            return
        reported.add(full)
        errors.append(
            f"{what} runs within {fab} minimum clearance {min_spacing}mm of the pour boundary; "
            "move it away from the pour or shrink the pour"
        )

    for zone in zones:
        for pad in pads:
            if pad.layer != zone.layer or (pad.net and pad.net == zone.net):
                continue
            if _point_in_polygon(pad.cx, pad.cy, zone.poly):
                continue  # enclosed — the pour clears it during fill
            gap = (
                _point_polygon_boundary_gap(pad.cx, pad.cy, zone.poly)
                - max(pad.width, pad.height) / 2
            )
            if _below(gap, min_spacing):
                report_edge(
                    zone.net,
                    pad.net,
                    f"pad {pad.number} of {pad.ref} (net {pad.net or 'unconnected'}) on "
                    f"{zone.layer}, outside the {zone.net or '?'} pour,",
                )
        for node in document.walk():
            if node.type == NODE_TRACK:
                if str(node.props.get("layer", "F.Cu")) != zone.layer:
                    continue
                net = str(node.props.get("net", ""))
                if net and net == zone.net:
                    continue
                start, end = node.props.get("start"), node.props.get("end")
                if not (isinstance(start, list) and isinstance(end, list)):
                    continue
                s = (float(start[0]), float(start[1]))
                e = (float(end[0]), float(end[1]))
                if _point_in_polygon(*s, zone.poly) or _point_in_polygon(*e, zone.poly):
                    continue  # enters the pour — handled by the pour's own clearance
                n = len(zone.poly)
                gap = (
                    min(
                        _segment_distance(s, e, zone.poly[i], zone.poly[(i + 1) % n])
                        for i in range(n)
                    )
                    - float(node.props.get("width", 0.0)) / 2
                )
                if _below(gap, min_spacing):
                    report_edge(
                        zone.net,
                        net,
                        f"track on net {net or '?'} on {zone.layer}, outside the "
                        f"{zone.net or '?'} pour,",
                    )
            elif node.type == NODE_VIA:
                net = str(node.props.get("net", ""))
                if net and net == zone.net:
                    continue
                at = node.props.get("at")
                if not (isinstance(at, list) and len(at) == 2):
                    continue
                vx, vy = float(at[0]), float(at[1])
                if _point_in_polygon(vx, vy, zone.poly):
                    continue
                gap = (
                    _point_polygon_boundary_gap(vx, vy, zone.poly)
                    - float(node.props.get("size", 0.0)) / 2
                )
                if _below(gap, min_spacing):
                    report_edge(
                        zone.net,
                        net,
                        f"via on net {net or '?'} at ({vx:g}, {vy:g}), outside the "
                        f"{zone.net or '?'} pour,",
                    )


def check_fab_rules(document: ForgeDocument, fab: str = DEFAULT_FAB) -> dict[str, Any]:
    """Validate a hardware document's design rules against a fab profile.

    Returns ``{"fab", "passed", "errors", "warnings"}``. For a non-hardware
    document the checks do not apply: ``passed`` is True with empty lists. Raises
    ``ValueError`` for an unknown fab name.
    """
    profile = _FAB_PROFILES.get(fab)
    if profile is None:
        raise ValueError(f"unknown fab {fab!r}; available: {', '.join(_FAB_PROFILES)}")

    errors: list[str] = []
    warnings: list[str] = []

    if document.domain != Domain.HARDWARE:
        return {"fab": fab, "passed": True, "errors": errors, "warnings": warnings}

    board = _board_node(document)
    if board is None:
        warnings.append("no board node found; cannot check fabrication rules")
        return {"fab": fab, "passed": True, "errors": errors, "warnings": warnings}

    rules = board.props.get("design_rules")
    if not isinstance(rules, dict):
        warnings.append("board has no design_rules; cannot check trace/via geometry")
    else:
        track_width = float(rules.get("track_width", 0.0))
        via_diameter = float(rules.get("via_diameter", 0.0))
        via_drill = float(rules.get("via_drill", 0.0))
        if _below(track_width, profile["min_trace_width"]):
            errors.append(
                f"track_width {track_width}mm is below {fab} minimum trace width "
                f"{profile['min_trace_width']}mm"
            )
        if _below(via_diameter, profile["min_via_diameter"]):
            errors.append(
                f"via_diameter {via_diameter}mm is below {fab} minimum via diameter "
                f"{profile['min_via_diameter']}mm"
            )
        if _below(via_drill, profile["min_via_drill"]):
            errors.append(
                f"via_drill {via_drill}mm is below {fab} minimum via drill "
                f"{profile['min_via_drill']}mm"
            )
        # drill_size is optional; only check it when both the document carries it
        # and the profile defines a minimum.
        drill_size = rules.get("drill_size")
        if drill_size is not None and "min_drill_size" in profile:
            if _below(float(drill_size), profile["min_drill_size"]):
                errors.append(
                    f"drill_size {float(drill_size)}mm is below {fab} minimum drill size "
                    f"{profile['min_drill_size']}mm"
                )

    _check_routed_copper(document, fab, profile, errors)
    _check_copper_collisions(document, fab, profile, errors)
    default_clearance = float(rules.get("clearance", 0.2)) if isinstance(rules, dict) else 0.2
    _check_zone_clearance(document, fab, profile, errors, default_clearance)

    # Board-size envelope — only when the profile defines limits and there is an
    # outline to measure.
    bounds = _outline_bounds(board.props.get("outline"))
    if "max_board_width" in profile:
        if bounds is None:
            warnings.append("board has no outline; cannot check board size")
        else:
            width, height = bounds
            for axis, value in (("width", width), ("height", height)):
                max_key, min_key = f"max_board_{axis}", f"min_board_{axis}"
                if max_key in profile and _above(value, profile[max_key]):
                    errors.append(
                        f"board {axis} {value}mm exceeds {fab} maximum {profile[max_key]}mm"
                    )
                if min_key in profile and _below(value, profile[min_key]):
                    errors.append(
                        f"board {axis} {value}mm is below {fab} minimum {profile[min_key]}mm"
                    )

    return {"fab": fab, "passed": not errors, "errors": errors, "warnings": warnings}


def check_gerber_completeness(document: ForgeDocument, fab: str = DEFAULT_FAB) -> dict[str, Any]:
    """Pre-flight for Gerber export: is this document worth sending to a fab?

    Returns ``{"ready", "fab", "errors", "warnings"}``. ``errors`` are the fab
    profile's hard violations (via ``check_fab_rules``, including the routed
    geometry checks) — ``ready`` is False while any exist. A board with no
    routed tracks gets a warning: the Gerbers would carry pads and outline but
    no connections, which is nearly useless to a fab — run ``route_board``
    first.
    """
    fab_result = check_fab_rules(document, fab)
    errors = list(fab_result["errors"])
    warnings = list(fab_result["warnings"])
    if document.domain == Domain.HARDWARE and not any(
        n.type == NODE_TRACK for n in document.walk()
    ):
        warnings.append(
            "board has no routed tracks — the Gerber set would contain no copper "
            "connections; run route_board (or hand-place track nodes) before export"
        )
    if document.domain == Domain.HARDWARE and any(n.type == NODE_ZONE for n in document.walk()):
        warnings.append(
            "board has copper zones — the Gerber exporter does not render pours yet, so "
            "the Gerber set would omit them; export to KiCad (which fills the zones) for now"
        )
    return {"ready": not errors, "fab": fab, "errors": errors, "warnings": warnings}
