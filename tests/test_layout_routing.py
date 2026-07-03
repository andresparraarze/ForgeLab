"""Grid-based maze routing (Lee's algorithm): 2-layer autorouting.

The guarantee under test is validity, not commercial trace quality: routed
tracks connect their pads, respect keepouts and clearance to other copper, and
unroutable nets are reported rather than crashing the whole operation.
"""

import json
import math
from pathlib import Path

import pytest

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.layout import RoutingError, route_document
from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION, ForgeDocument
from forgelab.validation import check_fab_rules

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _outline(width: float, height: float) -> list[dict]:
    corners = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]
    return [{"start": list(corners[i]), "end": list(corners[(i + 1) % 4])} for i in range(4)]


def _component(ref: str, at: list[float], pads: list[dict]) -> dict:
    return {
        "id": ref,
        "type": "component",
        "props": {
            "reference": ref,
            "value": "X",
            "footprint": f"Test:{ref}",
            "layer": "F.Cu",
            "at": at,
            "pads": pads,
        },
    }


def _pin(number: str, net: str, at: list[float], size: list[float] | None = None) -> dict:
    pad: dict = {"number": number, "net": net, "at": at}
    if size is not None:
        pad["size"] = size
    return pad


def _doc(
    components: list[dict],
    nets: list[str],
    width: float = 30.0,
    height: float = 20.0,
    extra_nodes: list[dict] | None = None,
) -> ForgeDocument:
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "route-me", "generator": "test"},
            "nodes": [
                {
                    "id": "board",
                    "type": "board",
                    "props": {
                        "kicad_version": "20240108",
                        "generator": "test",
                        "outline": _outline(width, height),
                        "design_rules": {
                            "clearance": 0.2,
                            "track_width": 0.25,
                            "via_diameter": 0.8,
                            "via_drill": 0.4,
                        },
                    },
                },
                *[
                    {"id": f"net_{name}", "type": "net", "props": {"code": i + 1, "name": name}}
                    for i, name in enumerate(nets)
                ],
                *components,
                *(extra_nodes or []),
            ],
        }
    )


def _net_tracks(result: dict, net: str) -> list[dict]:
    return [t for t in result["tracks"] if t["net"] == net]


def _endpoints_connected(tracks: list[dict], pads: list[list[float]], tol: float = 0.15) -> bool:
    """All pad positions belong to one connected component of the track graph.

    Endpoints are matched by rounded (x, y) — vias join layers at the same
    point, so connectivity is checked in the plane.
    """
    parent: dict[tuple, tuple] = {}

    def key(pt) -> tuple:
        return (round(pt[0], 4), round(pt[1], 4))

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    for t in tracks:
        union(key(t["start"]), key(t["end"]))
    pad_keys = []
    for pad in pads:
        nearest = min(parent, key=lambda k: math.dist(k, pad), default=None)
        if nearest is None or math.dist(nearest, pad) > tol:
            return False
        pad_keys.append(find(nearest))
    return len(set(pad_keys)) == 1


def _seg_point_dist(seg: dict, x: float, y: float) -> float:
    (x1, y1), (x2, y2) = seg["start"], seg["end"]
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.dist((x1, y1), (x, y))
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length2))
    return math.dist((x1 + t * dx, y1 + t * dy), (x, y))


# ----------------------------------------------------------------- basic route


def test_two_pad_net_routes_with_valid_path():
    doc = _doc(
        [
            _component("R1", [5.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])]),
            _component("R2", [25.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])]),
        ],
        nets=["SIG"],
    )
    result = route_document(doc)
    assert result["nets_routed"] == ["SIG"]
    assert result["nets_failed"] == []
    tracks = _net_tracks(result, "SIG")
    assert tracks, "expected at least one track segment"
    assert _endpoints_connected(tracks, [[5.0, 10.0], [25.0, 10.0]])
    # A straight 20mm connection should not meander.
    assert 20.0 - 0.3 <= result["total_track_length_mm"] <= 22.0
    for track in tracks:
        assert track["width"] == 0.25  # design_rules.track_width by default


def test_track_endpoints_stay_on_the_board():
    doc = _doc(
        [
            _component("R1", [1.0, 1.0], [_pin("1", "SIG", [0.0, 0.0])]),
            _component("R2", [29.0, 19.0], [_pin("1", "SIG", [0.0, 0.0])]),
        ],
        nets=["SIG"],
    )
    result = route_document(doc)
    for track in result["tracks"]:
        for pt in (track["start"], track["end"]):
            assert -1e-6 <= pt[0] <= 30.0 + 1e-6
            assert -1e-6 <= pt[1] <= 20.0 + 1e-6


# ------------------------------------------------------------------- keepouts


def test_route_avoids_component_keepout():
    # A wall of foreign pads from the bottom edge up to y=14 sits between the
    # two SIG pads; on a single layer the route must detour above the wall.
    wall_pads = [_pin(str(i), "", [0.0, -7.0 + i * 2.0], size=[1.0, 2.0]) for i in range(8)]
    doc = _doc(
        [
            _component("R1", [5.0, 5.0], [_pin("1", "SIG", [0.0, 0.0])]),
            _component("R2", [25.0, 5.0], [_pin("1", "SIG", [0.0, 0.0])]),
            _component("WALL", [15.0, 7.0], wall_pads),
        ],
        nets=["SIG"],
    )
    result = route_document(doc, layers=1)
    assert result["nets_routed"] == ["SIG"]
    tracks = _net_tracks(result, "SIG")
    assert max(max(t["start"][1], t["end"][1]) for t in tracks) > 14.0
    # No track point may land inside the wall's pad copper.
    for track in tracks:
        for pt in (track["start"], track["end"]):
            inside = 14.3 < pt[0] < 15.7 and pt[1] < 14.2
            assert not inside, f"track point {pt} inside the keepout wall"


def test_route_respects_clearance_to_existing_traces():
    # Net A (shorter span) routes first, straight along y=10 from board edge
    # to board edge of its pads; net B's pads are collinear with A, so B must
    # route around A's ends while keeping copper clearance.
    doc = _doc(
        [
            _component("A1", [8.0, 10.0], [_pin("1", "A", [0.0, 0.0])]),
            _component("A2", [22.0, 10.0], [_pin("1", "A", [0.0, 0.0])]),
            _component("B1", [4.0, 10.0], [_pin("1", "B", [0.0, 0.0])]),
            _component("B2", [26.0, 10.0], [_pin("1", "B", [0.0, 0.0])]),
        ],
        nets=["A", "B"],
    )
    result = route_document(doc, layers=1)
    assert sorted(result["nets_routed"]) == ["A", "B"]
    a_tracks = _net_tracks(result, "A")
    b_tracks = _net_tracks(result, "B")
    # Sample B's segments finely against A's segments: centreline separation
    # must never drop below track_width + clearance.
    min_sep = track_width_plus_clearance = 0.25 + 0.2
    for bt in b_tracks:
        (x1, y1), (x2, y2) = bt["start"], bt["end"]
        steps = max(1, int(math.dist((x1, y1), (x2, y2)) / 0.05))
        for i in range(steps + 1):
            x = x1 + (x2 - x1) * i / steps
            y = y1 + (y2 - y1) * i / steps
            for at in a_tracks:
                assert _seg_point_dist(at, x, y) >= min_sep - 1e-6, (
                    f"B point ({x}, {y}) within clearance of A track {at}"
                )
    assert min_sep == track_width_plus_clearance


# --------------------------------------------------------------- multi-pin MST


def test_three_pad_net_connects_all_pads():
    doc = _doc(
        [
            _component("G1", [5.0, 5.0], [_pin("1", "GND", [0.0, 0.0])]),
            _component("G2", [25.0, 5.0], [_pin("1", "GND", [0.0, 0.0])]),
            _component("G3", [15.0, 15.0], [_pin("1", "GND", [0.0, 0.0])]),
        ],
        nets=["GND"],
    )
    result = route_document(doc)
    assert result["nets_routed"] == ["GND"]
    tracks = _net_tracks(result, "GND")
    assert _endpoints_connected(tracks, [[5.0, 5.0], [25.0, 5.0], [15.0, 15.0]])


# ------------------------------------------------------------- failure handling


def test_blocked_net_fails_gracefully_and_is_reported():
    # The target pad is enclosed by a square ring of foreign copper; on a
    # single layer no path exists. The net must be reported, not crash.
    ring = []
    n = 0
    for i in range(-2, 3):
        for j in range(-2, 3):
            if max(abs(i), abs(j)) == 2:
                n += 1
                ring.append(_pin(str(n), "", [i * 1.0, j * 1.0], size=[1.0, 1.0]))
    doc = _doc(
        [
            _component("R1", [5.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])]),
            _component("R2", [20.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])]),
            _component("RING", [20.0, 10.0], ring),
        ],
        nets=["SIG"],
    )
    result = route_document(doc, layers=1)
    assert result["nets_routed"] == []
    assert result["nets_failed"] == ["SIG"]
    assert _net_tracks(result, "SIG") == []


def test_board_without_outline_raises_clearly():
    doc = _doc([_component("R1", [5.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])])], nets=["SIG"])
    doc.nodes[0].props["outline"] = []
    with pytest.raises(RoutingError, match="outline"):
        route_document(doc)


# ------------------------------------------------------------------------ vias


def test_via_inserted_when_route_must_change_layers():
    # Net B (shorter span) routes first, straight down x=15; net A then spans
    # the full board width along y=10 and must cross B, forcing a dive to
    # B.Cu and back.
    doc = _doc(
        [
            _component("A1", [0.0, 10.0], [_pin("1", "A", [0.0, 0.0])]),
            _component("A2", [30.0, 10.0], [_pin("1", "A", [0.0, 0.0])]),
            _component("B1", [15.0, 3.0], [_pin("1", "B", [0.0, 0.0])]),
            _component("B2", [15.0, 17.0], [_pin("1", "B", [0.0, 0.0])]),
        ],
        nets=["A", "B"],
    )
    result = route_document(doc)
    assert result["nets_failed"] == []
    assert result["vias_used"] >= 2
    a_vias = [v for v in result["vias"] if v["net"] == "A"]
    assert len(a_vias) >= 2
    for via in a_vias:
        assert via["size"] == 0.8 and via["drill"] == 0.4  # design_rules geometry
    assert any(t["layer"] == "B.Cu" for t in _net_tracks(result, "A"))


# ------------------------------------------------------------- KiCad S-exprs


def test_kicad_exporter_emits_segment_and_via_sexprs():
    doc = _doc(
        [_component("R1", [5.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])])],
        nets=["SIG"],
        extra_nodes=[
            {
                "id": "track_1",
                "type": "track",
                "props": {
                    "net": "SIG",
                    "layer": "B.Cu",
                    "start": [5.0, 10.0],
                    "end": [9.5, 10.0],
                    "width": 0.25,
                },
            },
            {
                "id": "via_1",
                "type": "via",
                "props": {"at": [9.5, 10.0], "net": "SIG", "size": 0.8, "drill": 0.4},
            },
        ],
    )
    text = KiCadExporter().from_ir(doc).decode("utf-8")
    assert "(segment" in text
    assert "(start 5 10)" in text and "(end 9.5 10)" in text
    assert '(layer "B.Cu")' in text
    assert "(width 0.25)" in text
    assert "(via" in text
    assert "(at 9.5 10)" in text and "(size 0.8)" in text and "(drill 0.4)" in text
    assert '(layers "F.Cu" "B.Cu")' in text
    assert "(net 1)" in text  # SIG's net code on the copper


# ------------------------------------------------------- fab rules on tracks


def _routed_doc(track_width: float, gap: float, via_size: float = 0.8) -> ForgeDocument:
    return _doc(
        [],
        nets=["A", "B"],
        extra_nodes=[
            {
                "id": "track_a",
                "type": "track",
                "props": {
                    "net": "A",
                    "layer": "F.Cu",
                    "start": [5.0, 10.0],
                    "end": [25.0, 10.0],
                    "width": track_width,
                },
            },
            {
                "id": "track_b",
                "type": "track",
                "props": {
                    "net": "B",
                    "layer": "F.Cu",
                    "start": [5.0, 10.0 + track_width + gap],
                    "end": [25.0, 10.0 + track_width + gap],
                    "width": track_width,
                },
            },
            {
                "id": "via_a",
                "type": "via",
                "props": {"at": [25.0, 10.0], "net": "A", "size": via_size, "drill": 0.4},
            },
        ],
    )


def test_check_fab_rules_validates_routed_geometry():
    ok = check_fab_rules(_routed_doc(track_width=0.25, gap=0.2))
    assert ok["passed"], ok["errors"]

    thin = check_fab_rules(_routed_doc(track_width=0.05, gap=0.5))
    assert not thin["passed"]
    assert any("track" in e and "0.05" in e for e in thin["errors"])

    tight = check_fab_rules(_routed_doc(track_width=0.25, gap=0.02))
    assert not tight["passed"]
    assert any("clearance" in e.lower() for e in tight["errors"])

    small_via = check_fab_rules(_routed_doc(track_width=0.25, gap=0.2, via_size=0.3))
    assert not small_via["passed"]
    assert any("via" in e and "0.3" in e for e in small_via["errors"])


# --------------------------------------------------------------- MCP route_board


def test_route_board_writes_track_nodes_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    doc = _doc(
        [
            _component("R1", [5.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])]),
            _component("R2", [25.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])]),
        ],
        nets=["SIG"],
    )
    (tmp_path / "in.forge.json").write_text(json.dumps(doc.model_dump(mode="json")))
    result = tools.route_board("in.forge.json", "routed.forge.json")
    assert result["routed"] is True
    assert result["nets_routed"] == 1
    assert result["nets_failed"] == []
    assert result["total_track_length_mm"] > 0

    routed = json.loads((tmp_path / "routed.forge.json").read_text())
    ForgeDocument.model_validate(routed)
    tracks = [n for n in routed["nodes"] if n["type"] == "track"]
    assert tracks and all(n["props"]["net"] == "SIG" for n in tracks)

    # Re-routing the routed document replaces the copper instead of stacking it.
    again = tools.route_board("routed.forge.json", "routed2.forge.json")
    assert again["routed"] is True
    routed2 = json.loads((tmp_path / "routed2.forge.json").read_text())
    assert len([n for n in routed2["nodes"] if n["type"] == "track"]) == len(tracks)


def test_route_board_reports_missing_outline_as_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    doc = _doc([_component("R1", [5.0, 10.0], [_pin("1", "SIG", [0.0, 0.0])])], nets=["SIG"])
    raw = doc.model_dump(mode="json")
    raw["nodes"][0]["props"]["outline"] = []
    (tmp_path / "in.forge.json").write_text(json.dumps(raw))
    result = tools.route_board("in.forge.json", "out.forge.json")
    assert result["routed"] is False
    assert "outline" in result["error"]
    assert not (tmp_path / "out.forge.json").exists()


def test_route_board_arduino_uno_places_then_routes_most_nets(tmp_path, monkeypatch):
    """The real-board benchmark: auto_place + route_board on the Arduino Uno.

    Empirical result at the default 0.2mm grid: 22 of 32 multi-pad nets route
    (~2s). The 10 failures are all escape congestion around U1, the 0.8mm-pitch
    QFP that shelf packing puts flush into the board corner (its pad ring ends
    0.5mm from two board edges, so half its escape channels don't exist), plus
    GND/+5V — the two highest-fanout nets, routed last, that lose their final
    MST edges once the board fills up. That is the honest baseline for a basic
    maze router on this board; the assertions carry a small margin so
    incidental placement changes don't flap the test, while a real regression
    (an ordering or clearance bug typically halves the count) still trips it.
    """
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    src = _EXAMPLES / "hardware/arduino_uno.forge.json"
    placed = tools.auto_place(str(src), "placed.forge.json")
    assert placed["placed"] is True
    result = tools.route_board("placed.forge.json", "routed.forge.json")
    assert result["routed"] is True
    total = result["nets_routed"] + len(result["nets_failed"])
    assert total >= 30  # the Uno has 32 nets with 2+ positioned pads
    assert result["nets_routed"] >= 19, result["nets_failed"]
    assert result["total_track_length_mm"] > 100.0
    assert result["vias_used"] > 0

    routed = json.loads((tmp_path / "routed.forge.json").read_text())
    doc = ForgeDocument.model_validate(routed)
    # The routed board still exports to KiCad with real copper in it.
    text = KiCadExporter().from_ir(doc).decode("utf-8")
    assert text.count("(segment") == len([n for n in routed["nodes"] if n["type"] == "track"])
