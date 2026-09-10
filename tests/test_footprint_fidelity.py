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
from forgelab.verify.kicad import drc_argv

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

    The fallback produced two 1.6mm squares at the footprint origin: touching,
    and therefore a short between whatever two nets the part connects. The real
    0603 has two separated rectangles — in KiCad 10, at +/-0.825mm and 0.8x0.95.

    Asserted on the properties rather than those exact numbers, because the
    numbers belong to whichever KiCad is installed and a library revision that
    nudges a pad by a hundredth of a millimetre is not a ForgeLab regression.
    What must hold for any revision is that the pads are apart, and that they
    are the rectangle the part actually has rather than a square.
    """
    pads = {p["number"]: p for p in kicad_library.pad_geometry(_R0603)}
    assert set(pads) == {"1", "2"}
    (x1, _y1), (x2, _y2) = pads["1"]["at"], pads["2"]["at"]
    width = pads["1"]["size"][0]
    assert abs(x2 - x1) > width, "the pads must not touch — that was the short"
    assert x1 == -x2 and x1 != 0.0, "a 0603 is symmetric about its origin"
    assert pads["1"]["size"][0] != pads["1"]["size"][1], "a real 0603 pad is not square"
    assert all(v < 1.6 for v in pads["1"]["size"]), "and is smaller than the 1.6mm default"


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


def test_wiring_a_pad_the_part_does_not_have_is_reported():
    """A warning rather than an error, because the answer is version-dependent.

    A USB-B's shell is one pad named "SH" in KiCad 9's library and two numbered
    5 and 6 in KiCad 7's. ForgeLab cannot call a document wrong for disagreeing
    with a library revision the user chose and it did not — but the pad will
    carry no net, so it has to say something.
    """
    doc = _doc(_R0603, pads=[{"number": "1", "net": "N1"}, {"number": "7", "net": "N1"}])
    errors, warnings = check_hardware(doc)
    assert any("does not have" in w and "7" in w for w in warnings)
    assert errors == []


# ------------------------------------------------------- KiCad's own last word


@requires_kicad_cli
@pytest.mark.parametrize("name", ["blinky", "blinky_led", "arduino_uno"])
def test_every_example_is_drc_clean_under_real_kicad(name, tmp_path):
    """The gate that was missing, and that all three examples used to fail.

    Before footprints were embedded, KiCad reported 23 mismatched footprints on
    the Uno and two genuine shorts on blinky. Nothing in the suite noticed,
    because nothing in the suite asked KiCad.

    Two properties, and the second matters as much as the first. Every DRC rule
    passes — no shorts, no clearance failures, no footprint mismatches. And every
    connection KiCad finds missing belongs to a net `route_board` already told
    the caller about: one it could not route, or one it answered with a copper
    pour. The router is basic by design and does not finish the Uno, and a pour's
    real fill is KiCad's to compute — but a net the router claims it wired with
    tracks may never come back unconnected. Nothing goes missing quietly.
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
        drc_argv(board, report),
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert report.exists(), proc.stderr
    report_json = json.loads(report.read_text())
    violations = report_json["violations"]

    # KiCad can only report a footprint mismatch if it can find the library to
    # compare against, and it needs a configured fp-lib-table for that. On a
    # machine that has never launched KiCad there is none, and the mismatch check
    # silently does not run — which would make this gate pass no matter how wrong
    # the footprints were. Fail loudly instead of passing vacuously.
    unconfigured = [
        v for v in violations if "does not include the footprint library" in v["description"]
    ]
    assert not unconfigured, (
        "KiCad has no footprint library table, so it never compared these "
        "footprints against the library — this gate proved nothing. Seed "
        "~/.config/kicad/<version>/fp-lib-table from "
        "/usr/share/kicad/template/fp-lib-table."
    )
    assert violations == [], [f"{v['type']}: {v['description']}" for v in violations]

    unconnected_nets = set()
    for item in report_json.get("unconnected_items", []):
        for entry in item.get("items", []):
            text = str(entry.get("description", ""))
            if "[" in text:
                unconnected_nets.add(text.split("[")[1].split("]")[0])
    # A poured net is "answered", not "proven connected": route_board places the
    # pour, KiCad computes the fill, and a pad the fill does not reach is exactly
    # the blind spot forgelab.validation.electrical documents.
    announced = set(routed["nets_failed"]) | set(routed["nets_poured"])
    assert unconnected_nets <= announced, (
        "KiCad found connections missing on nets the router claimed it wired: "
        f"{sorted(unconnected_nets - announced)}"
    )


# ------------------------------------------- libraries older than this machine's

_LEGACY_LIB = Path(__file__).resolve().parent / "fixtures" / "legacy_footprints"
_LEGACY_ID = "Legacy_SMD:R_Legacy_0603"


@pytest.fixture
def legacy_library(monkeypatch):
    """Point footprint discovery at a KiCad 7-era library.

    The installed library is whichever KiCad the user has, and the two eras spell
    the designator differently: KiCad 8 and earlier use `(fp_text reference ...)`,
    KiCad 9+ use `(property "Reference" ...)`. Developing against one and
    testing against the same one hid that completely — every footprint embedded
    from a distro KiCad kept the library's placeholder "REF**" as its
    designator, on every board, silently.
    """
    monkeypatch.setenv(kicad_library.FORGELAB_OVERRIDE, str(_LEGACY_LIB))
    kicad_library.reset_cache()
    yield
    monkeypatch.delenv(kicad_library.FORGELAB_OVERRIDE, raising=False)
    kicad_library.reset_cache()


def test_a_legacy_library_still_resolves(legacy_library):
    assert kicad_library.available()
    pads = {p["number"]: p for p in kicad_library.pad_geometry(_LEGACY_ID)}
    assert pads["1"]["at"] == [-0.825, 0.0]
    assert kicad_library.courtyard_bbox(_LEGACY_ID) is not None


def test_a_legacy_footprints_designator_is_substituted(legacy_library):
    """The bug this fixture exists for: "REF**" must not reach the board."""
    text = KiCadExporter().from_ir(_doc(_LEGACY_ID)).decode()
    fp = _footprint(text)
    texts = [n for n in fp if isinstance(n, list) and str(n[0]) == "fp_text"]
    by_kind = {str(n[1]): n[2] for n in texts}
    assert by_kind["reference"] == "R1", "the library placeholder reached the board"
    assert by_kind["value"] == "1k"
    assert "REF**" not in text


def test_a_legacy_footprint_still_carries_its_body(legacy_library):
    text = KiCadExporter().from_ir(_doc(_LEGACY_ID)).decode()
    assert "F.CrtYd" in text
    assert text.count('(pad "') == 2
