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
from typing import Any

from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.hardware import NODE_BOARD, NODE_TRACK, NODE_VIA

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
