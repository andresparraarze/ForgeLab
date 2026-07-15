"""Automatic component placement for hardware documents.

Agents are good at choosing components and nets and bad at hand-guessing XY
coordinates — the live failure modes are a header extending past the board
edge and components crammed on top of each other. This module packs components
inside the board outline with a simple shelf/row algorithm: sort by footprint
area (largest first), fill rows left-to-right, wrap when a row is full. It is
deliberately not optimal; what it guarantees is **zero overlap and zero
components outside the board outline**.

Each component's footprint is the bounding box of its pad copper (explicit
``size`` or the shared exporter default) grown by a keepout margin, so
placement respects real package size, not just the pad centre points. Components
marked ``locked: true`` keep their position and act as obstacles the others
pack around. Pure standard library; depends only on ``forgelab.spec``.
"""

from __future__ import annotations

import math
from typing import Any

from forgelab.spec import Domain, ForgeDocument, Node
from forgelab.spec.hardware import NODE_BOARD, NODE_COMPONENT, pad_default_size, pad_grid_offset

DEFAULT_KEEPOUT = 0.5

# Escape-channel inset for large components (mm): parts above the area
# threshold stay this far from every board edge so the maze router keeps
# escape room on all their sides. Packing a QFP flush into a board corner
# kills the escape routes on those sides. The default was chosen empirically
# against route_board on the Arduino Uno example: 5mm lifts it from 22 to 25
# routed nets, while 2-4mm just reshuffles the congestion (20-22).
DEFAULT_LARGE_INSET = 5.0

# A component counts as "large" (QFP/QFN/module — not a passive or header)
# when its keepout-inclusive footprint exceeds this absolute area. A
# board-relative fraction sounds appealing but fails at both ends: 5% of an
# Arduino-Uno-sized board is 183mm2 (misses every QFP), while 5% of a tiny
# 10x10mm board is 5mm2 (insets passives it has no room to inset). Escape
# needs follow the part's physical size, not the board's.
_LARGE_AREA_MIN = 50.0

# Footprint half-size (mm) assumed for a component whose pads carry no physical
# positions — there is nothing to measure, but it still occupies real space.
_FALLBACK_HALF = 1.0

_EPS = 1e-9


class PlacementError(ValueError):
    """Raised when a document cannot be auto-placed (no outline, no room...)."""


Rect = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


def rotate_offset(px: float, py: float, rotation_deg: float) -> tuple[float, float]:
    """Rotate a footprint-relative offset by the component rotation.

    The IR is Y-up with positive rotation counterclockwise (see
    ``forgelab.spec.hardware``), so this is the standard 2D rotation:
    ``(1, 0)`` at 90 degrees maps to ``(0, 1)``. Exporters and layout tools
    share this so routed copper, Gerbers and the KiCad rendering (which
    receives Y-flipped coordinates) agree on rotated components.
    """
    if rotation_deg % 360.0 == 0.0:
        return px, py
    theta = math.radians(rotation_deg)
    c, s = math.cos(theta), math.sin(theta)
    return px * c - py * s, px * s + py * c


def component_rotation(props: dict[str, Any]) -> float:
    """The component's rotation in degrees from its ``at`` (0 when absent)."""
    at = props.get("at")
    if isinstance(at, list) and len(at) >= 3:
        try:
            return float(at[2])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def component_bbox(
    props: dict[str, Any],
    keepout: float = DEFAULT_KEEPOUT,
    rotation: float | None = None,
) -> Rect:
    """Footprint bounding box relative to the component origin, keepout included.

    Covers the pads' **copper**, not just their centre points: each pad
    contributes its ``at`` offset grown by half its ``size`` (size-less pads
    use the shared pitch-aware default the exporters render — see
    ``forgelab.spec.hardware.pad_default_size``), then the whole box grows by
    ``keepout`` on every side. Pads without an ``at`` still occupy copper at
    the exporters' deterministic fallback grid, so they count too. A component
    with no pads at all falls back to a small default footprint rather than a
    zero-size point. Pad offsets are rotated by the component's ``at`` rotation
    (pass ``rotation`` to override — e.g. ``0.0`` when the component is about
    to be re-placed at rotation 0).
    """
    if rotation is None:
        rotation = component_rotation(props)
    pads = [p for p in props.get("pads") or [] if isinstance(p, dict)]
    default = pad_default_size([p.get("at") for p in pads])
    theta = math.radians(rotation)
    cos_r, sin_r = abs(math.cos(theta)), abs(math.sin(theta))
    xs: list[float] = []
    ys: list[float] = []
    for index, pad in enumerate(pads):
        at = pad.get("at")
        if isinstance(at, list) and len(at) == 2:
            ox, oy = float(at[0]), float(at[1])
        else:
            ox, oy = pad_grid_offset(index, len(pads))
        rx, ry = rotate_offset(ox, oy, rotation)
        size = pad.get("size")
        if isinstance(size, list) and len(size) == 2:
            w, h = float(size[0]), float(size[1])
        else:
            w = h = default
        # Axis-aligned extents of the rotated pad rectangle.
        half_w = (w * cos_r + h * sin_r) / 2
        half_h = (w * sin_r + h * cos_r) / 2
        xs.extend((rx - half_w, rx + half_w))
        ys.extend((ry - half_h, ry + half_h))
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


def place_components(
    document: ForgeDocument,
    keepout: float = DEFAULT_KEEPOUT,
    large_component_inset: float = DEFAULT_LARGE_INSET,
) -> dict[str, Any]:
    """Pack all non-locked components inside the board outline.

    Returns ``{"placements", "components_placed", "components_locked",
    "board_utilization"}`` where ``placements`` maps component node ids to
    their new ``[x, y, 0.0]`` positions (rotation is not considered — placed
    components sit at rotation 0) and ``board_utilization`` is the total
    footprint area (keepout included, locked components counted) as a
    percentage of the board outline's bounding-box area.

    Components whose footprint exceeds the large-part threshold (an absolute
    50mm2 — QFPs/QFNs/modules, not passives/headers) are kept
    ``large_component_inset`` millimetres away from every board edge so the
    autorouter keeps escape channels on all their sides; smaller parts pack
    flush as before. The zero-overlap and in-bounds guarantees are
    unchanged.

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
        if node.props.get("locked"):
            # Locked parts keep their position AND rotation: the obstacle is
            # their rotated footprint.
            bbox = component_bbox(node.props, keepout)
            at = node.props.get("at") or [0.0, 0.0]
            ox, oy = float(at[0]), float(at[1])
            obstacles.append((ox + bbox[0], oy + bbox[1], ox + bbox[2], oy + bbox[3]))
        else:
            # Movable parts are re-placed at rotation 0, so pack their
            # unrotated footprint regardless of any current rotation.
            movable.append((node, component_bbox(node.props, keepout, rotation=0.0)))

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
        # Large parts get an escape-channel inset from every board edge; the
        # effective packing bounds shrink for them, nothing else changes.
        inset = large_component_inset if w * h > _LARGE_AREA_MIN else 0.0
        lim_x, lim_y = x1 - inset, y1 - inset
        while True:
            place_x = max(cursor_x, x0 + inset)
            place_y = max(cursor_y, y0 + inset)
            if place_x + w > lim_x + _EPS:  # row full -> wrap to the next row
                if row_h > 0.0:
                    cursor_y += row_h
                else:
                    # Nothing fit in this row (e.g. a locked obstacle spans
                    # it): drop below the next obstacle edge — re-scanning the
                    # identical row would loop forever.
                    next_y = min(
                        (ob[3] for ob in obstacles if ob[3] > cursor_y + _EPS), default=None
                    )
                    if next_y is None:
                        raise _cannot_fit(len(components), board_w, board_h)
                    cursor_y = next_y
                cursor_x, row_h = x0, 0.0
                if max(cursor_y, y0 + inset) + h > lim_y + _EPS:
                    raise _cannot_fit(len(components), board_w, board_h)
                continue
            if place_y + h > lim_y + _EPS:
                raise _cannot_fit(len(components), board_w, board_h)
            rect = (place_x, place_y, place_x + w, place_y + h)
            hit = next((ob for ob in obstacles if _overlaps(rect, ob)), None)
            if hit is not None:
                cursor_x = max(place_x, hit[2])  # skip past the obstacle
                continue
            break
        placements[node.id] = [rect[0] - bbox[0], rect[1] - bbox[1], 0.0]
        obstacles.append(rect)
        cursor_x = rect[2]
        row_h = max(row_h, rect[3] - cursor_y)

    utilization = round(100.0 * footprint_area / board_area, 1) if board_area > 0 else 0.0
    return {
        "placements": placements,
        "components_placed": len(placements),
        "components_locked": len(components) - len(placements),
        "board_utilization": utilization,
    }
