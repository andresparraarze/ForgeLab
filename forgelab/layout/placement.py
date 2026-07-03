"""Automatic component placement for hardware documents.

Agents are good at choosing components and nets and bad at hand-guessing XY
coordinates — the live failure modes are a header extending past the board
edge and components crammed on top of each other. This module packs components
inside the board outline with a simple shelf/row algorithm: sort by footprint
area (largest first), fill rows left-to-right, wrap when a row is full. It is
deliberately not optimal; what it guarantees is **zero overlap and zero
components outside the board outline**.

Each component's footprint is its pad bounding box grown by a keepout margin,
so placement respects real package size, not just the origin point. Components
marked ``locked: true`` keep their position and act as obstacles the others
pack around. Pure standard library; depends only on ``forgelab.spec``.
"""

from __future__ import annotations

from typing import Any

from forgelab.spec import Domain, ForgeDocument, Node
from forgelab.spec.hardware import NODE_BOARD, NODE_COMPONENT

DEFAULT_KEEPOUT = 0.5

# Footprint half-size (mm) assumed for a component whose pads carry no physical
# positions — there is nothing to measure, but it still occupies real space.
_FALLBACK_HALF = 1.0

_EPS = 1e-9


class PlacementError(ValueError):
    """Raised when a document cannot be auto-placed (no outline, no room...)."""


Rect = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


def component_bbox(props: dict[str, Any], keepout: float = DEFAULT_KEEPOUT) -> Rect:
    """Footprint bounding box relative to the component origin, keepout included.

    Computed over the pads' physical ``at`` offsets (min/max x and y), grown by
    ``keepout`` on every side. A component with no positioned pads falls back
    to a small default footprint rather than a zero-size point.
    """
    xs: list[float] = []
    ys: list[float] = []
    for pad in props.get("pads") or []:
        at = pad.get("at") if isinstance(pad, dict) else None
        if isinstance(at, list) and len(at) == 2:
            xs.append(float(at[0]))
            ys.append(float(at[1]))
    if not xs:
        xs = [-_FALLBACK_HALF, _FALLBACK_HALF]
        ys = [-_FALLBACK_HALF, _FALLBACK_HALF]
    return (min(xs) - keepout, min(ys) - keepout, max(xs) + keepout, max(ys) + keepout)


def _board_bbox(document: ForgeDocument) -> Rect:
    board: Node | None = None
    for node in document.walk():
        if node.type == NODE_BOARD:
            board = node
            break
    if board is None:
        raise PlacementError("document has no board node; nothing to place within")
    outline = board.props.get("outline")
    xs: list[float] = []
    ys: list[float] = []
    for seg in outline or []:
        if not isinstance(seg, dict):
            continue
        for key in ("start", "end"):
            point = seg.get(key)
            if isinstance(point, list) and len(point) == 2:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
    if not xs:
        raise PlacementError(
            "board has no outline; auto placement needs a board outline to pack within"
        )
    return (min(xs), min(ys), max(xs), max(ys))


def _overlaps(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] - _EPS and b[0] < a[2] - _EPS and a[1] < b[3] - _EPS and b[1] < a[3] - _EPS


def _cannot_fit(count: int, width: float, height: float) -> PlacementError:
    return PlacementError(
        f"Cannot fit {count} components on a board of {width:g}x{height:g} mm — "
        f"consider increasing board size or removing components"
    )


def place_components(document: ForgeDocument, keepout: float = DEFAULT_KEEPOUT) -> dict[str, Any]:
    """Pack all non-locked components inside the board outline.

    Returns ``{"placements", "components_placed", "components_locked",
    "board_utilization"}`` where ``placements`` maps component node ids to
    their new ``[x, y, 0.0]`` positions (rotation is not considered — placed
    components sit at rotation 0) and ``board_utilization`` is the total
    footprint area (keepout included, locked components counted) as a
    percentage of the board outline's bounding-box area.

    Raises ``PlacementError`` when the document is not a hardware document,
    the board outline is missing, or the components cannot all fit.
    """
    if document.domain != Domain.HARDWARE:
        raise PlacementError("auto placement applies to hardware documents only")

    x0, y0, x1, y1 = _board_bbox(document)
    board_w, board_h = x1 - x0, y1 - y0
    board_area = board_w * board_h

    components = [n for n in document.walk() if n.type == NODE_COMPONENT]
    obstacles: list[Rect] = []
    movable: list[tuple[Node, Rect]] = []
    for node in components:
        bbox = component_bbox(node.props, keepout)
        if node.props.get("locked"):
            at = node.props.get("at") or [0.0, 0.0]
            ox, oy = float(at[0]), float(at[1])
            obstacles.append((ox + bbox[0], oy + bbox[1], ox + bbox[2], oy + bbox[3]))
        else:
            movable.append((node, bbox))

    footprint_area = 0.0
    for _node, bbox in movable:
        footprint_area += (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    for rect in obstacles:
        footprint_area += (rect[2] - rect[0]) * (rect[3] - rect[1])
    if footprint_area > board_area + _EPS:
        raise _cannot_fit(len(components), board_w, board_h)

    # Shelf packing: largest footprint first, rows filled left-to-right from
    # the board's top-left corner, wrapping down when a row is full. Locked
    # obstacles are skipped past horizontally; every placed rect also becomes
    # an obstacle, making the no-overlap invariant local and unconditional.
    movable.sort(key=lambda item: -(item[1][2] - item[1][0]) * (item[1][3] - item[1][1]))
    placements: dict[str, list[float]] = {}
    cursor_x, cursor_y, row_h = x0, y0, 0.0
    for node, bbox in movable:
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        while True:
            if cursor_x + w > x1 + _EPS:  # row full -> wrap to the next row
                cursor_y += row_h
                cursor_x, row_h = x0, 0.0
                if cursor_y + h > y1 + _EPS:
                    raise _cannot_fit(len(components), board_w, board_h)
                continue
            if cursor_y + h > y1 + _EPS:
                raise _cannot_fit(len(components), board_w, board_h)
            rect = (cursor_x, cursor_y, cursor_x + w, cursor_y + h)
            hit = next((ob for ob in obstacles if _overlaps(rect, ob)), None)
            if hit is not None:
                cursor_x = max(cursor_x, hit[2])  # skip past the obstacle
                continue
            break
        placements[node.id] = [rect[0] - bbox[0], rect[1] - bbox[1], 0.0]
        obstacles.append(rect)
        cursor_x = rect[2]
        row_h = max(row_h, h)

    utilization = round(100.0 * footprint_area / board_area, 1) if board_area > 0 else 0.0
    return {
        "placements": placements,
        "components_placed": len(placements),
        "components_locked": len(components) - len(placements),
        "board_utilization": utilization,
    }
