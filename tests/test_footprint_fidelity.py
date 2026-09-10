"""Real KiCad footprints, embedded rather than approximated.

ForgeLab names genuine library footprints. It used to invent their copper —
square pads from a shared default — so a board claimed a part while carrying
geometry that was not it. KiCad said so on every footprint of the Arduino Uno
(``lib_footprint_mismatch``), and where two invented pads landed on the same
point it was not merely inexact but a short between two nets.

These tests pin the fix from both ends: the library lookup and the transform in
isolation, and — where KiCad is installed — the whole pipeline against
``kicad-cli``'s own DRC, which is the only opinion that finally counts.
"""

import json
import subprocess
from pathlib import Path

import pytest
from external_tools import requires_kicad_cli

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.footprints import resolve as resolve_pads
from forgelab.footprints import unknown_pad_numbers
from forgelab.formats import kicad_library, parse
from forgelab.layout.routing import route_document
from forgelab.spec import SPEC_VERSION, DocumentMeta, Domain, ForgeDocument
from forgelab.validation import check_hardware

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "hardware"
_R0603 = "Resistor_SMD:R_0603_1608Metric"

pytestmark = pytest.mark.skipif(
    not kicad_library.available(),
    reason="KiCad's footprint libraries are not installed",
)


# ------------------------------------------------------------------ the lookup


def test_a_stock_footprint_resolves_to_a_file():
    path = kicad_library.resolve(_R0603)
    assert path is not None and path.is_file()
    assert path.suffix == ".kicad_mod"


@pytest.mark.parametrize(
    "lib_id",
    [
        "",
        "no-colon",
        "NoSuchLibrary:NoSuchFootprint",
        "Resistor_SMD:NoSuchFootprint",
        # A library id is not a path: neither separators nor traversal may
        # escape the library directory.
        "Resistor_SMD:../../../etc/passwd",
        "Resistor_SMD:sub/dir",
    ],
)
def test_unusable_ids_resolve_to_none(lib_id):
    assert kicad_library.resolve(lib_id) is None


def test_pad_geometry_is_the_real_thing():
    """The measurement that makes the whole change worth it.

    The 0603 resistor's real pads sit 1.65mm apart and are rectangular. The
    fallback produced two 1.6mm squares at the origin — touching, and therefore
    a short between whatever two nets the part connects.
    """
    pads = {p["number"]: p for p in kicad_library.pad_geometry(_R0603)}
    assert pads["1"]["at"] == [-0.825, 0.0]
    assert pads["2"]["at"] == [0.825, 0.0]
    assert pads["1"]["size"] == [0.8, 0.95]


def test_courtyard_is_larger_than_the_copper():
    """A part needs more board than its pads cover, and the library says so."""
    box = kicad_library.courtyard_bbox("Package_QFP:TQFP-32_7x7mm_P0.8mm")
    assert box is not None
    x0, y0, x1, y1 = box
    pads = kicad_library.pad_geometry("Package_QFP:TQFP-32_7x7mm_P0.8mm")
    pad_span = max(abs(p["at"][0]) for p in pads) * 2
    assert (x1 - x0) > pad_span


# --------------------------------------------------------------- the resolver


def test_the_library_defines_geometry_and_the_ir_defines_the_netlist():
    """IR geometry does not override a stock footprint — that is the fix.

    The blinky example asserted both pads were at (0, 0). Honouring that is what
    produced the short; the library is what the named part actually is.
    """
    ir = [
        {"number": "1", "net": "+3V3", "at": [0, 0], "size": [1.6, 1.6]},
        {"number": "2", "net": "LED_A", "at": [0, 0], "size": [1.6, 1.6]},
    ]
    pads = {p.number: p for p in resolve_pads(_R0603, ir)}
    assert (pads["1"].x, pads["2"].x) == (-0.825, 0.825)
    assert pads["1"].width == 0.8
    # The netlist still comes from the document.
    assert pads["1"].net == "+3V3" and pads["2"].net == "LED_A"


def test_an_unresolvable_footprint_falls_back_to_the_ir():
    ir = [{"number": "1", "net": "N", "at": [2.0, 3.0], "size": [1.0, 1.5]}]
    (pad,) = resolve_pads("NoSuchLibrary:NoSuchPart", ir)
    assert (pad.x, pad.y, pad.width, pad.height) == (2.0, 3.0, 1.0, 1.5)


def test_unknown_pad_numbers_are_reported():
    assert unknown_pad_numbers(_R0603, [{"number": "1"}, {"number": "9"}]) == ["9"]
    # Nothing is known about a footprint that does not resolve.
    assert unknown_pad_numbers("No:Thing", [{"number": "9"}]) == []


# ---------------------------------------------------------------- the exporter


def _doc(footprint: str, layer: str = "F.Cu", pads=None) -> ForgeDocument:
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": Domain.HARDWARE.value,
            "meta": DocumentMeta(name="t", generator="test").model_dump(),
            "nodes": [
                {
                    "id": "board",
                    "type": "board",
                    "props": {
                        "kicad_version": "20240108",
                        "generator": "pcbnew",
                        "outline": [
                            {"start": [0, 0], "end": [20, 0]},
                            {"start": [20, 0], "end": [20, 20]},
                            {"start": [20, 20], "end": [0, 20]},
                            {"start": [0, 20], "end": [0, 0]},
                        ],
                        "design_rules": {
                            "clearance": 0.2,
                            "track_width": 0.25,
                            "via_diameter": 0.8,
                            "via_drill": 0.4,
                        },
                    },
                },
                {"id": "net:1", "type": "net", "props": {"code": 1, "name": "N1"}},
                {
                    "id": "R1",
                    "type": "component",
                    "props": {
                        "reference": "R1",
                        "value": "1k",
                        "footprint": footprint,
                        "layer": layer,
                        "at": [10, 10, 0],
                        "pads": pads
                        or [
                            {"number": "1", "net": "N1"},
                            {"number": "2", "net": "N1"},
                        ],
                    },
                },
            ],
        }
    )


def _footprint(text: str) -> list:
    tree = parse(text)
    return next(n for n in tree if isinstance(n, list) and n and str(n[0]) == "footprint")


def test_embedded_footprint_carries_the_library_body():
    """Silkscreen, courtyard and fab outline come across, not just pads.

    KiCad compares a board's footprint against its library copy in full, so
    anything ForgeLab redraws itself is a reported mismatch.
    """
    fp = _footprint(KiCadExporter().from_ir(_doc(_R0603)).decode())
    layers = {
        str(child[1])
        for node in fp
        if isinstance(node, list)
        for child in node
        if isinstance(child, list) and child and str(child[0]) == "layer"
    }
    assert {"F.SilkS", "F.CrtYd", "F.Fab"} <= layers


def test_embedded_footprint_drops_the_standalone_file_tokens():
    """A board states its own format version; the footprint file's is not it."""
    fp = _footprint(KiCadExporter().from_ir(_doc(_R0603)).decode())
    tags = {str(node[0]) for node in fp if isinstance(node, list) and node}
    assert "version" not in tags and "generator" not in tags
    assert fp[1] == _R0603


def test_pads_are_the_librarys_and_carry_this_boards_nets():
    fp = _footprint(KiCadExporter().from_ir(_doc(_R0603)).decode())
    pads = [n for n in fp if isinstance(n, list) and str(n[0]) == "pad"]
    ats = sorted(next(c for c in p if isinstance(c, list) and str(c[0]) == "at")[1] for p in pads)
    assert ats == [-0.825, 0.825], "pads must not collapse onto the footprint origin"
    for pad in pads:
        net = next(c for c in pad if isinstance(c, list) and str(c[0]) == "net")
        assert net[2] == "N1"


def test_a_back_side_component_puts_its_copper_on_the_back():
    """A B.Cu part used to export with F.Cu pads and F.SilkS text — a board
    whose back-side parts were silently drawn on the front."""
    fp = _footprint(KiCadExporter().from_ir(_doc(_R0603, layer="B.Cu")).decode())
    pads = [n for n in fp if isinstance(n, list) and str(n[0]) == "pad"]
    assert pads
    for pad in pads:
        layers = next(c for c in pad if isinstance(c, list) and str(c[0]) == "layers")
        assert "F.Cu" not in [str(x) for x in layers[1:]]
        assert "B.Cu" in [str(x) for x in layers[1:]]
    text_layers = {
        str(next(c for c in node if isinstance(c, list) and str(c[0]) == "layer")[1])
        for node in fp
        if isinstance(node, list) and node and str(node[0]) == "property"
    }
    assert not any(layer.startswith("F.") for layer in text_layers), text_layers


# --------------------------------------------------------------- the reporting


def test_an_unresolvable_footprint_is_reported_not_silently_approximated():
    errors, warnings = check_hardware(_doc("NoSuchLibrary:NoSuchPart"))
    assert any("not in the installed KiCad libraries" in w for w in warnings)
    assert not errors


def test_wiring_a_pad_the_part_does_not_have_is_an_error():
    doc = _doc(_R0603, pads=[{"number": "1", "net": "N1"}, {"number": "7", "net": "N1"}])
    errors, _ = check_hardware(doc)
    assert any("does not have" in e and "7" in e for e in errors)


# ------------------------------------------------------- KiCad's own last word


@requires_kicad_cli
@pytest.mark.parametrize("name", ["blinky", "blinky_led", "arduino_uno"])
def test_every_example_is_drc_clean_under_real_kicad(name, tmp_path):
    """The gate that was missing, and that all three examples used to fail.

    Before footprints were embedded, KiCad reported 23 mismatched footprints on
    the Uno and two genuine shorts on blinky. Nothing in the suite noticed,
    because nothing in the suite asked KiCad.
    """
    data = json.loads((_EXAMPLES / f"{name}.forge.json").read_text())
    doc = ForgeDocument.model_validate(data)
    routed = route_document(doc)
    nodes = [n for n in data["nodes"] if n.get("type") not in ("track", "via", "zone")]
    for kind in ("tracks", "vias", "zones"):
        nodes.extend(
            {"id": f"{kind}_{i}", "type": kind[:-1], "props": props}
            for i, props in enumerate(routed[kind])
        )
    data["nodes"] = nodes

    board = tmp_path / f"{name}.kicad_pcb"
    board.write_bytes(KiCadExporter().from_ir(ForgeDocument.model_validate(data)))
    report = tmp_path / "drc.json"
    proc = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--severity-all", "--refill-zones",
         "--format", "json", "-o", str(report), str(board)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert report.exists(), proc.stderr
    violations = json.loads(report.read_text())["violations"]
    assert violations == [], [f"{v['type']}: {v['description']}" for v in violations]
