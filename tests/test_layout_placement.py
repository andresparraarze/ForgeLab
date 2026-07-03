"""Automatic component placement: shelf packing inside the board outline.

The guarantee under test is not optimality but correctness: zero component
overlap and zero components outside the board outline — the two live layout
bugs (a header past the board edge, cramped/overlapping parts).
"""

import json
from pathlib import Path

import pytest

from forgelab.layout import PlacementError, component_bbox, place_components
from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION, ForgeDocument

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _outline(width: float, height: float) -> list[dict]:
    corners = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]
    return [{"start": list(corners[i]), "end": list(corners[(i + 1) % 4])} for i in range(4)]


def _component(
    ref: str,
    half_w: float,
    half_h: float,
    at: list[float] | None = None,
    locked: bool = False,
) -> dict:
    props = {
        "reference": ref,
        "value": "X",
        "footprint": f"Test:{ref}",
        "layer": "F.Cu",
        "at": at or [0.0, 0.0, 0.0],
        "pads": [
            {"number": "1", "net": "N", "at": [-half_w, -half_h]},
            {"number": "2", "net": "N", "at": [half_w, half_h]},
        ],
    }
    if locked:
        props["locked"] = True
    return {"id": ref, "type": "component", "props": props}


def _doc(components: list[dict], width: float = 30.0, height: float = 20.0) -> ForgeDocument:
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "place-me", "generator": "test"},
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
                *components,
            ],
        }
    )


def _rects(document: ForgeDocument, placements: dict[str, list[float]], keepout: float = 0.5):
    """Placed footprint rects (keepout included) in board coordinates."""
    rects = {}
    for node in document.walk():
        if node.type != "component":
            continue
        at = placements.get(node.id) or node.props.get("at") or [0.0, 0.0]
        x0, y0, x1, y1 = component_bbox(node.props, keepout)
        rects[node.id] = (at[0] + x0, at[1] + y0, at[0] + x1, at[1] + y1)
    return rects


def _assert_no_overlap_and_in_bounds(rects: dict, width: float, height: float) -> None:
    eps = 1e-6
    ids = list(rects)
    for cid in ids:
        x0, y0, x1, y1 = rects[cid]
        assert x0 >= -eps and y0 >= -eps and x1 <= width + eps and y1 <= height + eps, (
            f"{cid} out of bounds: {rects[cid]}"
        )
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            ax0, ay0, ax1, ay1 = rects[a]
            bx0, by0, bx1, by1 = rects[b]
            overlap = ax0 < bx1 - eps and bx0 < ax1 - eps and ay0 < by1 - eps and by0 < ay1 - eps
            assert not overlap, f"{a} overlaps {b}: {rects[a]} vs {rects[b]}"


def test_simple_packing_fits_within_bounds_with_no_overlap():
    doc = _doc(
        [
            _component("U1", 4.0, 3.0),
            _component("R1", 0.8, 0.4),
            _component("C1", 0.8, 0.4),
            _component("J1", 2.5, 1.0),
        ]
    )
    result = place_components(doc)
    assert result["components_placed"] == 4
    assert result["components_locked"] == 0
    _assert_no_overlap_and_in_bounds(_rects(doc, result["placements"]), 30.0, 20.0)


def test_placed_components_sit_at_rotation_zero():
    doc = _doc([_component("U1", 2.0, 2.0, at=[5.0, 5.0, 90.0])])
    result = place_components(doc)
    assert result["placements"]["U1"][2] == 0.0


def test_locked_component_keeps_position_and_is_avoided():
    # J1 is manually placed mid-board and locked; the others must pack around
    # it without touching it or moving it.
    locked_at = [15.0, 10.0, 0.0]
    doc = _doc(
        [
            _component("U1", 4.0, 3.0),
            _component("R1", 0.8, 0.4),
            _component("J1", 3.0, 8.0, at=locked_at, locked=True),
        ]
    )
    result = place_components(doc)
    assert result["components_placed"] == 2
    assert result["components_locked"] == 1
    assert "J1" not in result["placements"]
    rects = _rects(doc, result["placements"])
    _assert_no_overlap_and_in_bounds(rects, 30.0, 20.0)
    # J1's rect is computed from its original (unchanged) position.
    assert rects["J1"] == (
        locked_at[0] - 3.5,
        locked_at[1] - 8.5,
        locked_at[0] + 3.5,
        locked_at[1] + 8.5,
    )


def test_packing_fails_clearly_when_board_is_too_small():
    doc = _doc([_component("U1", 6.0, 6.0), _component("U2", 6.0, 6.0)], width=10.0, height=10.0)
    with pytest.raises(PlacementError, match=r"Cannot fit 2 components on a board of 10x10 mm"):
        place_components(doc)


def test_board_without_outline_raises_clearly():
    doc = _doc([_component("U1", 1.0, 1.0)])
    doc.nodes[0].props["outline"] = []
    with pytest.raises(PlacementError, match="outline"):
        place_components(doc)


def test_board_utilization_is_footprint_area_over_board_area():
    # One component, pads spanning 4x2mm, keepout 0.5 -> footprint 5x3 = 15mm2
    # on a 30x20 = 600mm2 board -> 2.5%.
    doc = _doc([_component("U1", 2.0, 1.0)])
    result = place_components(doc)
    assert result["board_utilization"] == 2.5


def test_small_two_pad_component_packs_alongside_large_component():
    doc = _doc(
        [
            _component("U1", 8.0, 6.0),  # large multi-area part
            _component("R1", 0.8, 0.4),  # tiny 2-pad passive
        ]
    )
    result = place_components(doc)
    assert result["components_placed"] == 2
    _assert_no_overlap_and_in_bounds(_rects(doc, result["placements"]), 30.0, 20.0)


def test_component_with_no_positioned_pads_gets_fallback_footprint():
    node = _component("X1", 1.0, 1.0)
    node["props"]["pads"] = [{"number": "1", "net": "N"}]  # no physical 'at'
    x0, y0, x1, y1 = component_bbox(node["props"], 0.5)
    assert (x1 - x0, y1 - y0) == (3.0, 3.0)  # 2x2mm fallback + keepout


# ------------------------------------------------------------- MCP auto_place


def test_auto_place_arduino_uno_example_no_overlap_no_out_of_bounds(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    src = _EXAMPLES / "hardware/arduino_uno.forge.json"
    result = tools.auto_place(str(src), "placed.forge.json")
    assert result["placed"] is True
    assert result["components_placed"] > 0
    assert 0.0 < result["board_utilization"] <= 100.0

    placed = json.loads((tmp_path / "placed.forge.json").read_text())
    doc = ForgeDocument.model_validate(placed)
    board = next(n for n in doc.nodes if n.type == "board")
    xs = [p for seg in board.props["outline"] for pt in (seg["start"], seg["end"]) for p in [pt[0]]]
    ys = [p for seg in board.props["outline"] for pt in (seg["start"], seg["end"]) for p in [pt[1]]]
    rects = _rects(doc, {})
    _assert_no_overlap_and_in_bounds(
        {
            k: (r[0] - min(xs), r[1] - min(ys), r[2] - min(xs), r[3] - min(ys))
            for k, r in rects.items()
        },
        max(xs) - min(xs),
        max(ys) - min(ys),
    )


def test_auto_place_returns_error_dict_when_board_too_small(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    doc = _doc([_component("U1", 6.0, 6.0), _component("U2", 6.0, 6.0)], width=10.0, height=10.0)
    src = tmp_path / "small.forge.json"
    src.write_text(json.dumps(doc.model_dump(mode="json")))
    result = tools.auto_place("small.forge.json", "out.forge.json")
    assert result["placed"] is False
    assert "Cannot fit 2 components" in result["error"]
    assert not (tmp_path / "out.forge.json").exists()  # nothing written on failure
