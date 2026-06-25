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

from typing import Any

from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.hardware import NODE_BOARD

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
