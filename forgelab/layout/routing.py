"""Grid-based maze autorouting (Lee's algorithm) for hardware documents.

Turns a placed netlist into real copper: the board outline's bounding box is
discretized into a grid (two planes for a 2-layer board, joined by vias at a
cost penalty), each net's pads become fixed cells, and every connection is
found by a breadth-first flood fill that respects other nets' pads, already
routed traces (plus a clearance buffer), and the board edge. Multi-pin nets are
routed as a minimum spanning tree, each new pad connecting into the net's
existing copper. Nets the maze search cannot connect are recorded as failed
rather than aborting the whole board.

Copper is modelled physically, not as grid points: pads block their real
copper rectangle (explicit ``size`` or the shared exporter default) plus
clearance, pad offsets honor the component rotation, and **a via is a real
circle of ``via_diameter`` copper piercing every layer** — the search only
allows a layer change where the via barrel keeps ``clearance`` to every other
net's pads, tracks and vias (and a drill-to-drill margin to its own), else it
finds another path or fails the net cleanly. Pads without a physical ``at``
offset cannot be routed to, but their fallback-grid copper is still blocked.

This is deliberately a *basic* router: it produces valid, DRC-honest copper
for simple-to-moderate designs, not commercial-quality traces on dense ones.
Pure standard library; depends only on ``forgelab.spec``.
"""

from __future__ import annotations

import heapq
import math
from typing import Any

from forgelab.layout.placement import component_rotation, rotate_offset
from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.hardware import (
    DEFAULT_ZONE_MIN_THICKNESS,
    NODE_BOARD,
    NODE_COMPONENT,
    pad_default_size,
    pad_grid_offset,
)

# Minimum drill-to-drill wall (mm) between via holes, any net: closer than
# this the drill bit breaks into the neighbouring hole. KiCad's default
# hole-to-hole constraint; our design_rules carry no equivalent field.
_MIN_HOLE_TO_HOLE = 0.25

# Default grid pitch (mm per cell). Chosen empirically on the Arduino Uno
# example against *honest* copper obstacles (pads at their real rendered
# size, vias with their real diameter): 0.15mm routes 25/32 nets in ~4s,
# while 0.2mm manages only 17/32 (a 0.8mm-pitch QFP's escape corridors do
# not survive 0.2mm quantization, and the 0.45mm track+clearance halo
# rounds up to 0.6mm) and 0.1mm drops back to 20/32 at twice the runtime.
# 0.15 divides the default track_width + clearance (0.45mm) exactly.
DEFAULT_GRID_RESOLUTION = 0.15

# Extra path cost (in cell steps) for changing layers: vias are legal anywhere
# but expensive, so routes stay on one layer unless blocked.
_VIA_COST = 10

_LAYER_NAMES = ("F.Cu", "B.Cu")

# Auto-pour heuristic: a net the maze router could not connect becomes a filled
# copper plane only when it is genuinely pour-shaped — many pads fanned out
# across the board, the signature of a power/ground net. A signal net that
# merely lost to congestion has few pads in a small area and stays in
# nets_failed rather than being papered over with a plane it never asked for.
#
# The spread test deliberately measures reach in the *wider* axis plus overall
# area, not both axes independently: auto_place packs parts into a band, which
# compresses one axis of even a real ground net (the Arduino Uno's GND drops to
# ~34% of the board height once placed), so a strict both-axes rule would reject
# the very nets this is meant to catch. A plane must still reach across half the
# board in some direction and cover a real 2D fraction of it — a thin bus or a
# compact cluster does neither.
_POUR_MIN_PADS = 5  # strictly more than this many positioned pads
_POUR_MIN_BOARD_FRACTION = 0.5  # pad bbox must span >= this of the board in its wider axis
_POUR_MIN_AREA_FRACTION = 0.15  # pad bbox must cover >= this fraction of the board area

# Keep an auto-poured plane this far (mm) inside the board bounding box so it
# does not spill over the edge; KiCad's own edge clearance clips it further.
_POUR_EDGE_INSET = 0.5

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
        # Via legality, one layer-agnostic plane (a via pierces every layer):
        # _FREE = any net may via here, a net id = only that net, _BLOCKED =
        # nobody. Claimed by pad copper, routed copper and committed vias.
        self.via_owner = [_FREE] * (self.nx * self.ny)

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
        """Claim a rectangle of cells for ``net_id``.

        Where two different nets' rectangles overlap (adjacent pads whose
        clearance zones meet), the contested cells turn ``_BLOCKED`` for
        everyone: letting the later pad overwrite them would hand out cells
        that physically lie over the earlier pad's copper, and a track routed
        through those cells is a real short circuit.
        """
        i0 = max(0, math.ceil((x_min - self.x0) / self.res - _EPS))
        i1 = min(self.nx - 1, math.floor((x_max - self.x0) / self.res + _EPS))
        j0 = max(0, math.ceil((y_min - self.y0) / self.res - _EPS))
        j1 = min(self.ny - 1, math.floor((y_max - self.y0) / self.res + _EPS))
        owner = self.owner[layer]
        for j in range(j0, j1 + 1):
            base = j * self.nx
            for i in range(i0, i1 + 1):
                current = owner[base + i]
                if current == _FREE:
                    owner[base + i] = net_id
                elif current != net_id:
                    owner[base + i] = _BLOCKED

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

    def claim_via_zone(
        self, x_min: float, y_min: float, x_max: float, y_max: float, margin: float, net_id: int
    ) -> None:
        """Forbid foreign via centres within Euclidean ``margin`` of a copper rect.

        Stamps the layer-agnostic via plane: a cell claimed by one net stays
        legal for that net's own vias; a second net's claim (or ``_BLOCKED``)
        turns it illegal for everyone. Distance is exact point-to-rectangle,
        so a via barrel is kept ``margin`` from the copper edge, corners
        included. Exactly-at-margin stays legal (clearance is a minimum).
        """
        i0 = max(0, math.ceil((x_min - margin - self.x0) / self.res - _EPS))
        i1 = min(self.nx - 1, math.floor((x_max + margin - self.x0) / self.res + _EPS))
        j0 = max(0, math.ceil((y_min - margin - self.y0) / self.res - _EPS))
        j1 = min(self.ny - 1, math.floor((y_max + margin - self.y0) / self.res + _EPS))
        margin2 = margin * margin
        via_owner = self.via_owner
        for j in range(j0, j1 + 1):
            cy = self.y0 + j * self.res
            dy = max(y_min - cy, 0.0, cy - y_max)
            base = j * self.nx
            for i in range(i0, i1 + 1):
                cx = self.x0 + i * self.res
                dx = max(x_min - cx, 0.0, cx - x_max)
                if dx * dx + dy * dy >= margin2 - _EPS:
                    continue
                current = via_owner[base + i]
                if current == _FREE:
                    via_owner[base + i] = net_id
                elif current != net_id:
                    via_owner[base + i] = _BLOCKED


def _search(
    grid: _Grid, sources: set[tuple[int, int]], targets: set[tuple[int, int]], net_id: int
) -> list[tuple[int, int]] | None:
    """Dijkstra flood fill from ``sources`` to any cell in ``targets``.

    States are ``(layer, idx)``; orthogonal steps cost 1 and a layer change
    costs ``_VIA_COST``. Passable cells are free or already owned by this net;
    a layer change is additionally allowed only where the via plane permits
    this net, so a via's real copper diameter keeps clearance to other nets'
    pads, tracks and vias instead of being treated as a dimensionless point.
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
        if grid.via_owner[idx] not in (_FREE, net_id):
            continue  # a via here would violate clearance to another net's copper
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

    Returns ``{"tracks", "vias", "zones", "nets_routed", "nets_failed",
    "nets_poured", "total_track_length_mm", "vias_used"}`` —
    ``tracks``/``vias``/``zones`` are lists of ``Track``/``Via``/``Zone`` prop
    dicts ready to become IR nodes. Nets are routed in order of increasing pad
    bounding-box span so short, constrained connections go in before long ones
    can block them. A net whose maze search finds no path lands in
    ``nets_failed`` (already-routed edges of a partially routed multi-pin net
    are kept) and routing continues with the remaining nets.

    A failed net that is genuinely *pour-shaped* — a high-fanout, board-spanning
    power or ground net — is then turned into a filled copper plane instead of
    being reported as a failure (see ``_auto_pour``): it moves from
    ``nets_failed`` into ``nets_poured`` and gains a ``zone``. Signal nets that
    merely lost to congestion are left in ``nets_failed`` untouched.

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

    # Collect pads and stamp the copper obstacles — every pad blocks the copper
    # rectangle the exporters will actually render: its explicit ``size`` or
    # the shared pitch-aware default, plus clearance and half a track width so
    # a routed centreline keeps full edge-to-edge clearance from the copper.
    # Pads without an ``at`` cannot be routed to, but their fallback-grid
    # copper is still a real obstacle. Pad copper also claims the via plane so
    # no other net may via within via_diameter/2 + clearance of it. Routable
    # centres are re-stamped last so a pad's own connection point always
    # belongs to its own net, even where footprint rectangles overlap.
    track_margin = rules["clearance"] + rules["track_width"] / 2
    via_pad_margin = rules["via_diameter"] / 2 + rules["clearance"]
    net_ids: dict[str, int] = {}
    net_pads: dict[str, list[tuple[float, float]]] = {}
    centres: list[tuple[int, int]] = []  # (cell idx, net id) re-stamped after rects
    for node in document.walk():
        if node.type != NODE_COMPONENT:
            continue
        at = node.props.get("at") or [0.0, 0.0]
        cx, cy = float(at[0]), float(at[1])
        rotation = component_rotation(node.props)
        theta = math.radians(rotation)
        cos_r, sin_r = abs(math.cos(theta)), abs(math.sin(theta))
        pads = [p for p in node.props.get("pads") or [] if isinstance(p, dict)]
        default = pad_default_size([p.get("at") for p in pads])
        for index, pad in enumerate(pads):
            offset = pad.get("at")
            if isinstance(offset, list) and len(offset) == 2:
                routable = True
                ox, oy = float(offset[0]), float(offset[1])
            else:
                routable = False
                ox, oy = pad_grid_offset(index, len(pads))
            rx, ry = rotate_offset(ox, oy, rotation)
            px, py = cx + rx, cy + ry
            net = str(pad.get("net", ""))
            if net:
                net_id = net_ids.setdefault(net, len(net_ids) + 1)
                if routable:
                    net_pads.setdefault(net, []).append((px, py))
            else:
                net_id = _BLOCKED
            size = pad.get("size")
            if isinstance(size, list) and len(size) == 2:
                width, height = float(size[0]), float(size[1])
            else:
                width, height = default, default
            # Copper extents: the axis-aligned bbox of the (possibly rotated)
            # pad rectangle.
            half_w = (width * cos_r + height * sin_r) / 2
            half_h = (width * sin_r + height * cos_r) / 2
            grid.mark_rect(
                0,
                px - half_w - track_margin,
                py - half_h - track_margin,
                px + half_w + track_margin,
                py + half_h + track_margin,
                net_id,
            )
            grid.claim_via_zone(
                px - half_w, py - half_h, px + half_w, py + half_h, via_pad_margin, net_id
            )
            if routable:
                centres.append((grid.cell(px, py), net_id))
    for idx, net_id in centres:
        grid.owner[0][idx] = net_id

    # Clearance halo around routed copper, in cells: another net's centreline
    # must stay at least track_width + clearance away, and the first cell past
    # the halo is (radius + 1) cells out.
    halo = max(1, math.ceil((rules["track_width"] + rules["clearance"]) / grid_resolution) - 1)
    # A via's copper is wider than a track, so committed vias push foreign
    # track centrelines further out than the ordinary halo does.
    via_halo = max(
        halo,
        math.ceil(
            (rules["via_diameter"] / 2 + rules["track_width"] / 2 + rules["clearance"])
            / grid_resolution
        )
        - 1,
    )
    # Foreign via centres must clear routed track copper edge-to-edge; track
    # centrelines are sampled at cell points, so widen by half a cell to cover
    # the worst case between samples.
    via_track_margin = math.hypot(
        rules["via_diameter"] / 2 + rules["track_width"] / 2 + rules["clearance"],
        grid_resolution / 2,
    )
    # Via barrels of different nets keep full clearance; via holes of ANY net
    # keep a drill-to-drill wall (closer and the drill breaks through).
    via_via_margin = rules["via_diameter"] + rules["clearance"]
    hole_margin = rules["via_drill"] + _MIN_HOLE_TO_HOLE

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
            # Vias committed earlier are fenced off in the via plane, but two
            # layer changes chosen within this single search are not; refuse
            # the path rather than commit drill holes that break into each
            # other.
            if any(
                math.dist(a["at"], b["at"]) < hole_margin - _EPS
                for i, a in enumerate(new_vias)
                for b in new_vias[i + 1 :]
            ):
                failed = True
                break
            tracks.extend(new_tracks)
            vias.extend(new_vias)
            for layer, idx in path:
                grid.owner[layer][idx] = net_id
                grid.mark_buffer(layer, idx, halo, net_id)
                # Routed copper repels foreign via barrels edge-to-edge.
                tx, ty = grid.point(idx)
                grid.claim_via_zone(tx, ty, tx, ty, via_track_margin, net_id)
            # A via occupies every plane at its cell, pushes foreign tracks
            # out by its real radius, and keeps other via barrels (any-net
            # drill holes) at clearance.
            for (layer_a, idx_a), (layer_b, _idx_b) in zip(path, path[1:], strict=False):
                if layer_a != layer_b:
                    vx, vy = grid.point(idx_a)
                    for other in range(layers):
                        grid.owner[other][idx_a] = net_id
                        grid.mark_buffer(other, idx_a, via_halo, net_id)
                    grid.claim_via_zone(vx, vy, vx, vy, via_via_margin, net_id)
                    grid.claim_via_zone(vx, vy, vx, vy, hole_margin, _BLOCKED)
            connected.update(path)
        (nets_failed if failed else nets_routed).append(net)

    zones, nets_poured = _auto_pour(bbox, rules, net_pads, nets_failed, layers)
    nets_failed = [n for n in nets_failed if n not in set(nets_poured)]

    total = sum(math.dist(t["start"], t["end"]) for t in tracks)
    return {
        "tracks": tracks,
        "vias": vias,
        "zones": zones,
        "nets_routed": nets_routed,
        "nets_failed": nets_failed,
        "nets_poured": nets_poured,
        "total_track_length_mm": round(total, 2),
        "vias_used": len(vias),
    }


def _auto_pour(
    bbox: tuple[float, float, float, float],
    rules: dict[str, float],
    net_pads: dict[str, list[tuple[float, float]]],
    nets_failed: list[str],
    layers: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn genuinely pour-shaped failed nets into filled copper planes.

    A net qualifies only when it has more than ``_POUR_MIN_PADS`` positioned
    pads *and* those pads span at least ``_POUR_MIN_BOARD_FRACTION`` of the
    board in both width and height — the fanned-out, board-spanning shape of a
    ground or power net, not a local signal that lost to congestion. Qualifying
    nets are poured largest-fanout first: the biggest takes ``F.Cu`` (where
    ForgeLab's SMD pads live, so the plane connects them immediately), the next
    takes ``B.Cu`` (a classic 2-layer ground/power split, which connects once
    the pads are made through-hole via KiCad's "Update Footprints from
    Library"). One plane per copper layer — any further pour-shaped net can't
    fit another full-board plane and stays in ``nets_failed``.

    Returns ``(zones, nets_poured)``: zone prop dicts ready to become IR nodes,
    and the names of the nets that were poured.
    """
    x0, y0, x1, y1 = bbox
    board_w, board_h = x1 - x0, y1 - y0
    if board_w <= 0 or board_h <= 0:
        return [], []

    def pour_shaped(net: str) -> bool:
        pts = net_pads.get(net, [])
        if len(pts) <= _POUR_MIN_PADS:
            return False
        span_x = max(p[0] for p in pts) - min(p[0] for p in pts)
        span_y = max(p[1] for p in pts) - min(p[1] for p in pts)
        reaches = (
            span_x >= _POUR_MIN_BOARD_FRACTION * board_w
            or span_y >= _POUR_MIN_BOARD_FRACTION * board_h
        )
        covers = (span_x * span_y) >= _POUR_MIN_AREA_FRACTION * board_w * board_h
        return reaches and covers

    candidates = sorted(
        (n for n in nets_failed if pour_shaped(n)),
        key=lambda n: len(net_pads[n]),
        reverse=True,
    )
    inset = max(rules["clearance"], _POUR_EDGE_INSET)
    xa, xb = round(x0 + inset, 6), round(x1 - inset, 6)
    ya, yb = round(y0 + inset, 6), round(y1 - inset, 6)

    zones: list[dict[str, Any]] = []
    nets_poured: list[str] = []
    for layer_name, net in zip(_LAYER_NAMES[:layers], candidates, strict=False):
        zones.append(
            {
                "net": net,
                "layer": layer_name,
                "polygon": [[xa, ya], [xb, ya], [xb, yb], [xa, yb]],
                "clearance": rules["clearance"],
                "min_thickness": DEFAULT_ZONE_MIN_THICKNESS,
            }
        )
        nets_poured.append(net)
    return zones, nets_poured
