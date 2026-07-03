"""Grid-based maze autorouting (Lee's algorithm) for hardware documents.

Turns a placed netlist into real copper: the board outline's bounding box is
discretized into a grid (two planes for a 2-layer board, joined by vias at a
cost penalty), each net's pads become fixed cells, and every connection is
found by a breadth-first flood fill that respects other nets' pads, already
routed traces (plus a clearance buffer), and the board edge. Multi-pin nets are
routed as a minimum spanning tree, each new pad connecting into the net's
existing copper. Nets the maze search cannot connect are recorded as failed
rather than aborting the whole board.

This is deliberately a *basic* router: it produces a valid, DRC-clean routed
board for simple-to-moderate designs, not commercial-quality traces on dense
ones. Pads without a physical ``at`` offset cannot be located and are skipped;
component rotation is ignored (``auto_place`` leaves everything at rotation 0).
Pure standard library; depends only on ``forgelab.spec``.
"""

from __future__ import annotations

import heapq
import math
from typing import Any

from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.hardware import NODE_BOARD, NODE_COMPONENT

DEFAULT_GRID_RESOLUTION = 0.2

# Extra path cost (in cell steps) for changing layers: vias are legal anywhere
# but expensive, so routes stay on one layer unless blocked.
_VIA_COST = 10

_LAYER_NAMES = ("F.Cu", "B.Cu")

# Everything is on-grid, so coordinate comparisons tolerate float noise only.
_EPS = 1e-9

# owner-grid sentinel values; positive integers are net ids.
_FREE = 0
_BLOCKED = -1  # copper with no net (e.g. an unconnected pad): nobody may cross


class RoutingError(ValueError):
    """Raised when a document cannot be routed at all (no board outline...)."""


def _board_bbox(document: ForgeDocument) -> tuple[float, float, float, float]:
    board = next((n for n in document.walk() if n.type == NODE_BOARD), None)
    if board is None:
        raise RoutingError("document has no board node; nothing to route within")
    xs: list[float] = []
    ys: list[float] = []
    for seg in board.props.get("outline") or []:
        if not isinstance(seg, dict):
            continue
        for key in ("start", "end"):
            point = seg.get(key)
            if isinstance(point, list) and len(point) == 2:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
    if not xs:
        raise RoutingError("board has no outline; routing needs a board outline to stay within")
    return (min(xs), min(ys), max(xs), max(ys))


def _design_rules(document: ForgeDocument) -> dict[str, float]:
    board = next((n for n in document.walk() if n.type == NODE_BOARD), None)
    rules = board.props.get("design_rules") if board is not None else None
    rules = rules if isinstance(rules, dict) else {}
    return {
        "clearance": float(rules.get("clearance", 0.2)),
        "track_width": float(rules.get("track_width", 0.25)),
        "via_diameter": float(rules.get("via_diameter", 0.8)),
        "via_drill": float(rules.get("via_drill", 0.4)),
    }


class _Grid:
    """Two (or one) planes of cell ownership over the board's bounding box."""

    def __init__(self, bbox: tuple[float, float, float, float], resolution: float, layers: int):
        self.x0, self.y0, x1, y1 = bbox
        self.res = resolution
        self.nx = max(2, int(math.floor((x1 - self.x0) / resolution + _EPS)) + 1)
        self.ny = max(2, int(math.floor((y1 - self.y0) / resolution + _EPS)) + 1)
        self.layers = layers
        self.owner = [[_FREE] * (self.nx * self.ny) for _ in range(layers)]

    def cell(self, x: float, y: float) -> int:
        i = min(self.nx - 1, max(0, round((x - self.x0) / self.res)))
        j = min(self.ny - 1, max(0, round((y - self.y0) / self.res)))
        return j * self.nx + i

    def point(self, idx: int) -> list[float]:
        j, i = divmod(idx, self.nx)
        return [round(self.x0 + i * self.res, 6), round(self.y0 + j * self.res, 6)]

    def mark_rect(
        self, layer: int, x_min: float, y_min: float, x_max: float, y_max: float, net_id: int
    ) -> None:
        i0 = max(0, math.ceil((x_min - self.x0) / self.res - _EPS))
        i1 = min(self.nx - 1, math.floor((x_max - self.x0) / self.res + _EPS))
        j0 = max(0, math.ceil((y_min - self.y0) / self.res - _EPS))
        j1 = min(self.ny - 1, math.floor((y_max - self.y0) / self.res + _EPS))
        owner = self.owner[layer]
        for j in range(j0, j1 + 1):
            base = j * self.nx
            for i in range(i0, i1 + 1):
                owner[base + i] = net_id

    def mark_buffer(self, layer: int, idx: int, radius: int, net_id: int) -> None:
        """Claim free cells within Chebyshev ``radius`` of ``idx`` for ``net_id``.

        Only free cells are claimed: pad cells and other nets' copper keep
        their owner, so a clearance halo never swallows a connection point.
        """
        j, i = divmod(idx, self.nx)
        owner = self.owner[layer]
        for jj in range(max(0, j - radius), min(self.ny - 1, j + radius) + 1):
            base = jj * self.nx
            for ii in range(max(0, i - radius), min(self.nx - 1, i + radius) + 1):
                if owner[base + ii] == _FREE:
                    owner[base + ii] = net_id


def _search(
    grid: _Grid, sources: set[tuple[int, int]], targets: set[tuple[int, int]], net_id: int
) -> list[tuple[int, int]] | None:
    """Dijkstra flood fill from ``sources`` to any cell in ``targets``.

    States are ``(layer, idx)``; orthogonal steps cost 1 and a layer change
    costs ``_VIA_COST``. Passable cells are free or already owned by this net.
    Returns the cell path source -> target, or None when the search exhausts
    the grid.
    """
    nx, n = grid.nx, grid.nx * grid.ny
    owner = grid.owner
    dist = [[-1] * n for _ in range(grid.layers)]
    prev: list[list[int]] = [[-1] * n for _ in range(grid.layers)]
    heap: list[tuple[int, int, int]] = []
    for layer, idx in sources:
        dist[layer][idx] = 0
        heapq.heappush(heap, (0, layer, idx))

    end: tuple[int, int] | None = None
    while heap:
        cost, layer, idx = heapq.heappop(heap)
        if cost > dist[layer][idx]:
            continue
        if (layer, idx) in targets:
            end = (layer, idx)
            break
        row_start = (idx // nx) * nx
        neighbours = []
        if idx - 1 >= row_start:
            neighbours.append(idx - 1)
        if idx + 1 < row_start + nx:
            neighbours.append(idx + 1)
        if idx - nx >= 0:
            neighbours.append(idx - nx)
        if idx + nx < n:
            neighbours.append(idx + nx)
        layer_dist, layer_prev, layer_owner = dist[layer], prev[layer], owner[layer]
        for nb in neighbours:
            if layer_owner[nb] not in (_FREE, net_id):
                continue
            new_cost = cost + 1
            if layer_dist[nb] == -1 or new_cost < layer_dist[nb]:
                layer_dist[nb] = new_cost
                layer_prev[nb] = layer * n + idx
                heapq.heappush(heap, (new_cost, layer, nb))
        for other in range(grid.layers):
            if other == layer or owner[other][idx] not in (_FREE, net_id):
                continue
            new_cost = cost + _VIA_COST
            if dist[other][idx] == -1 or new_cost < dist[other][idx]:
                dist[other][idx] = new_cost
                prev[other][idx] = layer * n + idx
                heapq.heappush(heap, (new_cost, other, idx))

    if end is None:
        return None
    path: list[tuple[int, int]] = []
    layer, idx = end
    while True:
        path.append((layer, idx))
        if (layer, idx) in sources:
            break
        encoded = prev[layer][idx]
        layer, idx = divmod(encoded, n)
    path.reverse()
    return path


def _path_to_copper(
    grid: _Grid, path: list[tuple[int, int]], net: str, rules: dict[str, float]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert a cell path to merged track segments plus vias at layer changes."""
    tracks: list[dict[str, Any]] = []
    vias: list[dict[str, Any]] = []

    def close_segment(start_idx: int, end_idx: int, layer: int) -> None:
        if start_idx == end_idx:
            return
        tracks.append(
            {
                "net": net,
                "layer": _LAYER_NAMES[layer],
                "start": grid.point(start_idx),
                "end": grid.point(end_idx),
                "width": rules["track_width"],
            }
        )

    seg_start = path[0][1]
    direction: tuple[int, int] | None = None
    for (layer_a, idx_a), (layer_b, idx_b) in zip(path, path[1:], strict=False):
        if layer_a != layer_b:
            close_segment(seg_start, idx_a, layer_a)
            vias.append(
                {
                    "at": grid.point(idx_a),
                    "net": net,
                    "size": rules["via_diameter"],
                    "drill": rules["via_drill"],
                }
            )
            seg_start, direction = idx_b, None
            continue
        step = (idx_b - idx_a) % grid.nx, (idx_b - idx_a) // grid.nx
        if direction is not None and step != direction:
            close_segment(seg_start, idx_a, layer_a)
            seg_start = idx_a
        direction = step
    close_segment(seg_start, path[-1][1], path[-1][0])
    return tracks, vias


def _mst_order(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """Prim's MST over pad points: edges as (in-tree index, new index)."""
    in_tree = {0}
    edges: list[tuple[int, int]] = []
    best: dict[int, tuple[float, int]] = {}
    for i in range(1, len(points)):
        best[i] = (math.dist(points[0], points[i]), 0)
    while best:
        new = min(best, key=lambda i: best[i][0])
        edges.append((best.pop(new)[1], new))
        in_tree.add(new)
        for i, (d, _) in list(best.items()):
            nd = math.dist(points[new], points[i])
            if nd < d:
                best[i] = (nd, new)
    return edges


def route_document(
    document: ForgeDocument,
    grid_resolution: float = DEFAULT_GRID_RESOLUTION,
    layers: int = 2,
) -> dict[str, Any]:
    """Route every multi-pad net of a placed hardware document.

    Returns ``{"tracks", "vias", "nets_routed", "nets_failed",
    "total_track_length_mm", "vias_used"}`` — ``tracks``/``vias`` are lists of
    ``Track``/``Via`` prop dicts ready to become IR nodes. Nets are routed in
    order of increasing pad bounding-box span so short, constrained connections
    go in before long ones can block them. A net whose maze search finds no
    path lands in ``nets_failed`` (already-routed edges of a partially routed
    multi-pin net are kept) and routing continues with the remaining nets.

    Raises ``RoutingError`` for a non-hardware document or a missing outline.
    """
    if document.domain != Domain.HARDWARE:
        raise RoutingError("routing applies to hardware documents only")
    if layers not in (1, 2):
        raise RoutingError("layers must be 1 (F.Cu only) or 2 (F.Cu + B.Cu)")
    if grid_resolution <= 0:
        raise RoutingError("grid_resolution must be positive (millimetres per cell)")

    bbox = _board_bbox(document)
    rules = _design_rules(document)
    grid = _Grid(bbox, grid_resolution, layers)

    # Collect positioned pads and stamp the copper obstacles. Pads with a known
    # size block their copper rectangle plus clearance on F.Cu; pads with
    # unknown geometry block only their centre cell. Centres are re-stamped
    # last so a pad's own connection point always belongs to its own net, even
    # where footprint rectangles overlap.
    net_ids: dict[str, int] = {}
    net_pads: dict[str, list[tuple[float, float]]] = {}
    centres: list[tuple[int, int]] = []  # (cell idx, net id) re-stamped after rects
    for node in document.walk():
        if node.type != NODE_COMPONENT:
            continue
        at = node.props.get("at") or [0.0, 0.0]
        cx, cy = float(at[0]), float(at[1])
        for pad in node.props.get("pads") or []:
            if not isinstance(pad, dict):
                continue
            offset = pad.get("at")
            if not (isinstance(offset, list) and len(offset) == 2):
                continue  # no physical position: nothing to route to
            px, py = cx + float(offset[0]), cy + float(offset[1])
            net = str(pad.get("net", ""))
            if net:
                net_id = net_ids.setdefault(net, len(net_ids) + 1)
                net_pads.setdefault(net, []).append((px, py))
            else:
                net_id = _BLOCKED
            size = pad.get("size")
            if isinstance(size, list) and len(size) == 2:
                half_w = float(size[0]) / 2 + rules["clearance"]
                half_h = float(size[1]) / 2 + rules["clearance"]
                grid.mark_rect(0, px - half_w, py - half_h, px + half_w, py + half_h, net_id)
            else:
                grid.owner[0][grid.cell(px, py)] = net_id
            centres.append((grid.cell(px, py), net_id))
    for idx, net_id in centres:
        grid.owner[0][idx] = net_id

    # Clearance halo around routed copper, in cells: another net's centreline
    # must stay at least track_width + clearance away, and the first cell past
    # the halo is (radius + 1) cells out.
    halo = max(1, math.ceil((rules["track_width"] + rules["clearance"]) / grid_resolution) - 1)

    tracks: list[dict[str, Any]] = []
    vias: list[dict[str, Any]] = []
    nets_routed: list[str] = []
    nets_failed: list[str] = []

    def span(net: str) -> float:
        xs = [p[0] for p in net_pads[net]]
        ys = [p[1] for p in net_pads[net]]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    for net in sorted((n for n in net_pads if len(net_pads[n]) >= 2), key=span):
        net_id = net_ids[net]
        points = net_pads[net]
        pad_cell = {i: (0, grid.cell(*points[i])) for i in range(len(points))}
        # Cells already wired into the net's tree — targets for the next MST
        # edge, so later pads connect into the existing copper, not back to
        # the first pad. Pads not yet routed are deliberately NOT targets.
        connected: set[tuple[int, int]] = {pad_cell[0]}
        failed = False
        for _tree_i, new_i in _mst_order(points):
            path = _search(grid, {pad_cell[new_i]}, connected, net_id)
            if path is None:
                failed = True
                break
            new_tracks, new_vias = _path_to_copper(grid, path, net, rules)
            tracks.extend(new_tracks)
            vias.extend(new_vias)
            for layer, idx in path:
                grid.owner[layer][idx] = net_id
                grid.mark_buffer(layer, idx, halo, net_id)
            # A via occupies every plane at its cell.
            for (layer_a, idx_a), (layer_b, _idx_b) in zip(path, path[1:], strict=False):
                if layer_a != layer_b:
                    for other in range(layers):
                        grid.owner[other][idx_a] = net_id
                        grid.mark_buffer(other, idx_a, halo, net_id)
            connected.update(path)
        (nets_failed if failed else nets_routed).append(net)

    total = sum(math.dist(t["start"], t["end"]) for t in tracks)
    return {
        "tracks": tracks,
        "vias": vias,
        "nets_routed": nets_routed,
        "nets_failed": nets_failed,
        "total_track_length_mm": round(total, 2),
        "vias_used": len(vias),
    }
