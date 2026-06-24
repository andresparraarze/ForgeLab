"""Infer shared dimensions from a domain document.

The single high-value inference today: read a hardware board's outline and pull
its overall width and height into the project's shared table, so an enclosure or
render document can be sized from the real board footprint instead of a guess.
"""

from __future__ import annotations

from typing import Any


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


def infer_shared(document: dict[str, Any]) -> dict[str, float]:
    """Infer shared dimensions from a single document.

    For a hardware document, reads the first ``board`` node's outline and returns
    ``{"board_width", "board_height"}`` (millimetres) from its bounding box.
    Returns an empty dict when nothing can be inferred (non-hardware document, no
    board node, or a degenerate outline).
    """
    if document.get("domain") != "hardware":
        return {}
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return {}
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "board":
            continue
        props = node.get("props")
        if not isinstance(props, dict):
            continue
        bounds = _outline_bounds(props.get("outline"))
        if bounds is None:
            return {}
        return {"board_width": bounds[0], "board_height": bounds[1]}
    return {}
