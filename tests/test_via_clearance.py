"""Via clearance: the router places real copper cylinders, not grid points.

Regression armor for a real trust bug: route_board treated vias as
dimensionless, so it parked them on top of foreign pads and other vias —
KiCad DRC on a routed board found genuine short circuits (a via landing on a
+5V pad, via pairs closer than their own diameter) while check_fabrication
said ``passed: true``. These tests pin both halves of the fix: the router
never produces such copper, and check_fab_rules catches it when a document
carries it anyway.
"""

import json
import math
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.layout import place_components, route_document
from forgelab.spec import SPEC_VERSION, ForgeDocument, Node
from forgelab.validation import check_fab_rules

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# Design rules shared by the synthetic boards (the library defaults).
_CLEARANCE = 0.2
_VIA_DIAMETER = 0.8
_TRACK_WIDTH = 0.25
_PAD_SIZE = 1.0


def _board_doc(components: list[dict], nets: list[str], size: float = 30.0) -> ForgeDocument:
    corners = [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]
    outline = [{"start": list(corners[i]), "end": list(corners[(i + 1) % 4])} for i in range(4)]
    nodes: list[dict] = [
        {
            "id": "board",
            "type": "board",
            "props": {
                "kicad_version": "20240108",
                "generator": "test",
                "outline": outline,
                "design_rules": {
                    "clearance": _CLEARANCE,
                    "track_width": _TRACK_WIDTH,
                    "via_diameter": _VIA_DIAMETER,
                    "via_drill": 0.4,
                },
            },
        },
        *(
            {"id": f"net_{n}", "type": "net", "props": {"code": i + 1, "name": n}}
            for i, n in enumerate(nets)
        ),
        *components,
    ]
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "via-clearance", "generator": "test"},
            "nodes": nodes,
        }
    )


def _pin(ref: str, net: str, at: list[float]) -> dict:
    return {
        "id": ref,
        "type": "component",
        "props": {
            "reference": ref,
            "value": "X",
            "footprint": f"Test:{ref}",
            "layer": "F.Cu",
            "at": [*at, 0.0],
            "pads": [{"number": "1", "net": net, "at": [0.0, 0.0], "size": [_PAD_SIZE, _PAD_SIZE]}],
        },
    }


def _crossing_board(seed: int) -> tuple[ForgeDocument, list[tuple[str, float, float]]]:
    """A board whose nets all cross, forcing the router onto B.Cu via vias.

    Left-column pads connect to right-column pads in reversed (plus jittered)
    order, so every net crosses every other; on two layers that demands layer
    changes. Returns the document plus every pad's (net, x, y).
    """
    rng = random.Random(seed)
    n = 6
    comps: list[dict] = []
    pads: list[tuple[str, float, float]] = []
    nets = [f"N{i}" for i in range(n)]
    order = list(reversed(range(n)))
    # Shuffle a little so each seed is a different crossing pattern.
    for _ in range(seed % 4):
        i, j = rng.randrange(n), rng.randrange(n)
        order[i], order[j] = order[j], order[i]
    for i in range(n):
        ly = 4.0 + i * 4.0 + rng.uniform(-0.5, 0.5)
        ry = 4.0 + order[i] * 4.0 + rng.uniform(-0.5, 0.5)
        left = _pin(f"L{i}", nets[i], [4.0 + rng.uniform(0.0, 1.0), ly])
        right = _pin(f"R{i}", nets[i], [25.0 + rng.uniform(0.0, 1.0), ry])
        comps.extend((left, right))
        for comp in (left, right):
            at = comp["props"]["at"]
            pads.append((nets[i], at[0], at[1]))
    return _board_doc(comps, nets), pads


@pytest.mark.parametrize("seed", range(8))
def test_router_keeps_via_clearance_to_foreign_pads_and_vias(seed):
    document, pads = _crossing_board(seed)
    result = route_document(document)
    for via in result["vias"]:
        vx, vy = via["at"]
        via_r = via["size"] / 2
        for (
            net,
            px,
            py,
        ) in pads:
            if net == via["net"]:
                continue
            # Exact distance from the via centre to the pad's copper square.
            gap = (
                math.hypot(
                    max(abs(vx - px) - _PAD_SIZE / 2, 0.0),
                    max(abs(vy - py) - _PAD_SIZE / 2, 0.0),
                )
                - via_r
            )
            assert gap >= _CLEARANCE - 1e-6, (
                f"seed {seed}: via on {via['net']} at ({vx}, {vy}) is {gap:.3f}mm "
                f"from a pad on {net}"
            )
    for i, a in enumerate(result["vias"]):
        for b in result["vias"][i + 1 :]:
            if a["net"] == b["net"]:
                continue
            gap = math.dist(a["at"], b["at"]) - (a["size"] + b["size"]) / 2
            assert gap >= _CLEARANCE - 1e-6, (
                f"seed {seed}: vias on {a['net']}/{b['net']} at {a['at']} and "
                f"{b['at']} are {gap:.3f}mm apart"
            )


def test_crossing_boards_actually_exercise_vias():
    # The property test above is vacuous if the synthetic boards never via;
    # prove the crossing pattern forces real layer changes.
    total_vias = 0
    total_routed = 0
    for seed in range(8):
        document, _ = _crossing_board(seed)
        result = route_document(document)
        total_vias += result["vias_used"]
        total_routed += len(result["nets_routed"])
    assert total_vias > 0, "no synthetic board produced a single via"
    assert total_routed > 8, "crossing boards barely route; the property test proves nothing"


# ------------------------------------------------------- check_fab_rules side


def _via(node_id: str, net: str, at: list[float], size: float = 0.8) -> dict:
    return {
        "id": node_id,
        "type": "via",
        "props": {"at": at, "net": net, "size": size, "drill": 0.4},
    }


def test_check_fab_rules_catches_via_on_foreign_pad():
    # The exact scenario KiCad DRC caught in the wild: a via parked on a +5V
    # pad while carrying a different net. That is copper-on-copper — a short.
    doc = _board_doc(
        [_pin("U1", "+5V", [10.0, 10.0]), _via("via_d13", "D13", [10.0, 10.0])],
        nets=["+5V", "D13"],
    )
    result = check_fab_rules(doc)
    assert result["passed"] is False
    assert any("+5V" in e and "D13" in e and "short" in e for e in result["errors"]), result[
        "errors"
    ]


def test_check_fab_rules_catches_via_pair_inside_clearance():
    # Two vias 0.1mm apart (centre to centre) on different nets: their 0.8mm
    # barrels overlap by 0.7mm — the second confirmed-real DRC failure.
    doc = _board_doc(
        [_via("via_a", "A", [5.0, 5.0]), _via("via_b", "B", [5.1, 5.0])],
        nets=["A", "B"],
    )
    result = check_fab_rules(doc)
    assert result["passed"] is False
    assert any("vias on nets A and B" in e and "short" in e for e in result["errors"]), result[
        "errors"
    ]


def test_check_fab_rules_allows_same_net_via_in_pad():
    # Same-net contact is one conductor, not a short: via-in-pad stays legal.
    doc = _board_doc(
        [_pin("U1", "+5V", [10.0, 10.0]), _via("via_5v", "+5V", [10.0, 10.0])],
        nets=["+5V"],
    )
    result = check_fab_rules(doc)
    assert result["passed"] is True, result["errors"]


def test_check_fab_rules_catches_track_over_foreign_pad():
    # The largest short category on the broken board: a track routed straight
    # across another net's pad copper.
    doc = _board_doc(
        [
            _pin("U1", "SIG", [10.0, 10.0]),
            {
                "id": "track_gnd",
                "type": "track",
                "props": {
                    "net": "GND",
                    "layer": "F.Cu",
                    "start": [5.0, 10.0],
                    "end": [15.0, 10.0],
                    "width": _TRACK_WIDTH,
                },
            },
        ],
        nets=["SIG", "GND"],
    )
    result = check_fab_rules(doc)
    assert result["passed"] is False
    assert any("track" in e and "SIG" in e and "short" in e for e in result["errors"]), result[
        "errors"
    ]


# ------------------------------------------------- kicad-cli DRC ground truth


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not installed")
def test_routed_uno_export_is_short_free_under_kicad_drc(tmp_path):
    """KiCad's own DRC is the ground truth the fix was verified against.

    Place and route the Arduino Uno example, export it, and run kicad-cli
    drc: there must be no shorting items and no copper clearance or hole
    violations. (Footprint-library bookkeeping — lib_footprint_* — is
    metadata about our generated footprints not existing in KiCad's stock
    libraries, and carries no copper meaning.)
    """
    doc = ForgeDocument.model_validate(
        json.loads((_EXAMPLES / "hardware/arduino_uno.forge.json").read_text())
    )
    placed = place_components(doc)
    for node in doc.walk():
        if node.id in placed["placements"]:
            node.props["at"] = placed["placements"][node.id]
    result = route_document(doc)
    nodes = list(doc.nodes)
    nodes.extend(
        Node(id=f"track_{i}", type="track", props=t) for i, t in enumerate(result["tracks"])
    )
    nodes.extend(Node(id=f"via_{i}", type="via", props=v) for i, v in enumerate(result["vias"]))
    routed = doc.model_copy(update={"nodes": nodes})

    board = tmp_path / "uno_routed.kicad_pcb"
    board.write_bytes(KiCadExporter().from_ir(routed))
    report = tmp_path / "drc.json"
    proc = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "-o", str(report), str(board)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert report.exists(), proc.stderr
    violations = json.loads(report.read_text())["violations"]
    copper = [v for v in violations if not v["type"].startswith("lib_footprint")]
    assert copper == [], [f"{v['type']}: {v['description']}" for v in copper]
