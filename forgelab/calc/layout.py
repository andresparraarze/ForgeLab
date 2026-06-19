"""Simple board placement helper: a margin-aware grid of component positions."""

from __future__ import annotations

import math


def calculate_board_layout(
    component_count: int,
    board_width: float,
    board_height: float,
    margin: float = 2.0,
    reference_prefix: str = "U",
) -> list[dict[str, object]]:
    """Suggest grid placements for components inside a board outline.

    Spreads ``component_count`` components over a regular grid that fits the
    usable area (the board minus ``margin`` on every side), so an agent does not
    have to plan coordinates by hand. The grid's column/row split tracks the
    board's aspect ratio.

    Args:
        component_count: number of components to place (>= 1).
        board_width: board outline width, in millimetres.
        board_height: board outline height, in millimetres.
        margin: keep-out border on every edge, in millimetres. Defaults to 2.0.
        reference_prefix: prefix for generated references (``"U"`` -> U1, U2, ...).

    Returns:
        A list of ``{"reference": str, "at": [x, y]}`` dicts. ``at`` is the
        component centre in millimetres, with the origin at the board's
        lower-left corner.
    """
    if component_count < 1:
        raise ValueError("component_count must be >= 1")
    usable_w = board_width - 2.0 * margin
    usable_h = board_height - 2.0 * margin
    if usable_w <= 0 or usable_h <= 0:
        raise ValueError("margin is too large for the board outline")

    cols = max(1, round(math.sqrt(component_count * usable_w / usable_h)))
    cols = min(cols, component_count)
    rows = math.ceil(component_count / cols)
    cell_w = usable_w / cols
    cell_h = usable_h / rows

    placements: list[dict[str, object]] = []
    for index in range(component_count):
        row, col = divmod(index, cols)
        x = margin + cell_w * (col + 0.5)
        y = margin + cell_h * (row + 0.5)
        placements.append(
            {"reference": f"{reference_prefix}{index + 1}", "at": [round(x, 4), round(y, 4)]}
        )
    return placements
