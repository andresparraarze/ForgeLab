"""Copper pours (zones): fabrication checks and KiCad DRC ground truth.

Zones are emitted as *unfilled* boundaries — KiCad computes the actual poured
copper. ForgeLab therefore checks the boundary and the pour's declared
parameters conservatively (it may warn about a boundary the fill never reaches,
but never silently misses a short), and the real fill-clearance is verified by
running kicad-cli's own DRC with --refill-zones, exactly the ground truth the
router's copper was pinned against.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.layout import place_components, route_document
from forgelab.spec import SPEC_VERSION, ForgeDocument, Node
from forgelab.validation import check_fab_rules
from forgelab.validation.fabrication import check_gerber_completeness

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

_OUTLINE = [
    {"start": [0, 0], "end": [40, 0]},
    {"start": [40, 0], "end": [40, 30]},
    {"start": [40, 30], "end": [0, 30]},
    {"start": [0, 30], "end": [0, 0]},
]


def _doc(
    zones: list[dict], extra: list[dict] | None = None, clearance: float = 0.2
) -> ForgeDocument:
    nodes: list[dict] = [
        {
            "id": "board",
            "type": "board",
            "props": {
                "kicad_version": "20240108",
                "generator": "test",
                "outline": _OUTLINE,
                "design_rules": {
                    "clearance": clearance,
                    "track_width": 0.25,
                    "via_diameter": 0.8,
                    "via_drill": 0.4,
                },
            },
        },
        {"id": "net_GND", "type": "net", "props": {"code": 1, "name": "GND"}},
        {"id": "net_SIG", "type": "net", "props": {"code": 2, "name": "SIG"}},
    ]
    nodes += [{"id": f"zone_{i}", "type": "zone", "props": z} for i, z in enumerate(zones)]
    nodes += extra or []
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "z", "generator": "test"},
            "nodes": nodes,
        }
    )


# A GND pour filling most of the board.
_GND_POUR = {"net": "GND", "layer": "F.Cu", "polygon": [[2, 2], [20, 2], [20, 28], [2, 28]]}


def test_zone_clearance_below_fab_minimum_is_flagged():
    zone = {**_GND_POUR, "clearance": 0.05}  # below jlcpcb 0.1mm min spacing
    result = check_fab_rules(_doc([zone]))
    assert result["passed"] is False
    assert any("clearance" in e and "0.05" in e for e in result["errors"])


def test_zone_min_thickness_below_fab_minimum_is_flagged():
    zone = {**_GND_POUR, "min_thickness": 0.05}  # below jlcpcb 0.1mm min trace width
    result = check_fab_rules(_doc([zone]))
    assert result["passed"] is False
    assert any("min_thickness" in e for e in result["errors"])


def test_overlapping_same_layer_different_net_zones_are_flagged():
    a = {"net": "GND", "layer": "F.Cu", "polygon": [[2, 2], [20, 2], [20, 28], [2, 28]]}
    b = {"net": "SIG", "layer": "F.Cu", "polygon": [[10, 2], [38, 2], [38, 28], [10, 28]]}
    result = check_fab_rules(_doc([a, b]))
    assert result["passed"] is False
    assert any("overlap" in e for e in result["errors"])


def test_zones_on_different_layers_do_not_overlap_flag():
    a = {"net": "GND", "layer": "F.Cu", "polygon": [[2, 2], [38, 2], [38, 28], [2, 28]]}
    b = {"net": "SIG", "layer": "B.Cu", "polygon": [[2, 2], [38, 2], [38, 28], [2, 28]]}
    result = check_fab_rules(_doc([a, b]))
    # Same footprint, different copper layers — a classic 2-layer plane split.
    assert not any("overlap" in e for e in result["errors"])


def test_zone_vs_track_clearance_violation_is_caught():
    # A SIG track just outside the GND pour's right edge (x=20): 0.05mm away,
    # 0.25mm wide, so its copper is inside the fab clearance of the boundary the
    # pour fills up to.
    track = {
        "id": "t1",
        "type": "track",
        "props": {
            "net": "SIG",
            "layer": "F.Cu",
            "start": [20.05, 6],
            "end": [20.05, 24],
            "width": 0.25,
        },
    }
    result = check_fab_rules(_doc([_GND_POUR], extra=[track]))
    assert result["passed"] is False
    assert any("pour boundary" in e for e in result["errors"])


def test_track_enclosed_by_pour_is_not_flagged():
    # A foreign track *inside* the pour is fine — KiCad clears around it during
    # fill (governed by the zone clearance, checked separately).
    track = {
        "id": "t1",
        "type": "track",
        "props": {
            "net": "SIG",
            "layer": "F.Cu",
            "start": [6, 15],
            "end": [16, 15],
            "width": 0.25,
        },
    }
    result = check_fab_rules(_doc([_GND_POUR], extra=[track]))
    assert not any("pour boundary" in e for e in result["errors"])


def test_clean_zone_board_passes():
    assert check_fab_rules(_doc([_GND_POUR]))["passed"] is True


def test_gerber_completeness_warns_about_unrendered_zones():
    result = check_gerber_completeness(_doc([_GND_POUR]))
    assert any("zone" in w or "pour" in w for w in result["warnings"])


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not installed")
def test_zone_export_is_copper_clean_under_kicad_drc(tmp_path):
    """KiCad's own DRC, with the zones refilled, is the ground truth.

    Place and route the Arduino Uno (which auto-pours GND and +5V), export it,
    and run kicad-cli drc with --refill-zones so KiCad computes the real poured
    copper. There must be no error-level copper violations — no shorts, no
    clearance errors, and no starved-thermal errors (the reason the pour uses a
    solid pad connection rather than thermal relief). ``isolated_copper`` is a
    warning, not an error: the +5V B.Cu plane cannot connect to F.Cu-only SMD
    pads until they are made through-hole (the known SMD-pad limitation), so
    KiCad reports it as a warning — excluded here along with footprint-library
    bookkeeping and unconnected pads, none of which is a copper short.
    """
    doc = ForgeDocument.model_validate(
        json.loads((_EXAMPLES / "hardware/arduino_uno.forge.json").read_text())
    )
    placed = place_components(doc)
    for node in doc.walk():
        if node.id in placed["placements"]:
            node.props["at"] = placed["placements"][node.id]
    result = route_document(doc)
    assert set(result["nets_poured"]) == {"GND", "+5V"}

    nodes = list(doc.nodes)
    nodes += [Node(id=f"track_{i}", type="track", props=t) for i, t in enumerate(result["tracks"])]
    nodes += [Node(id=f"via_{i}", type="via", props=v) for i, v in enumerate(result["vias"])]
    nodes += [Node(id=f"zone_{i}", type="zone", props=z) for i, z in enumerate(result["zones"])]
    routed = doc.model_copy(update={"nodes": nodes})

    board = tmp_path / "uno_zones.kicad_pcb"
    board.write_bytes(KiCadExporter().from_ir(routed))
    assert board.read_text().count("(zone ") == 2

    report = tmp_path / "drc.json"
    proc = subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            "--refill-zones",
            "--format",
            "json",
            "-o",
            str(report),
            str(board),
        ],  # fmt: skip
        capture_output=True,
        text=True,
        check=False,
    )
    assert report.exists(), proc.stderr
    violations = json.loads(report.read_text())["violations"]
    errors = [
        v
        for v in violations
        if v.get("severity") == "error" and not v["type"].startswith("lib_footprint")
    ]
    assert errors == [], [f"{v['type']}: {v['description']}" for v in errors]
