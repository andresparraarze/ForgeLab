"""Gerber (RS-274X) + Excellon export: a fab-ready layer set in a zip.

Validation runs at two levels: structural assertions on the emitted text
(headers, apertures, draw/flash commands) and — with the same rigor as the
FreeCAD verification — a real parse of every layer with gerbonara, an actual
Gerber/Excellon parser, including full layer-set recognition on the routed
Arduino Uno example.
"""

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from forgelab.core import validate
from forgelab.exporters.hardware.gerber import GerberExporter
from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION
from forgelab.validation import check_gerber_completeness

gerbonara = pytest.importorskip("gerbonara", reason="gerbonara (dev dep) not installed")

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

_LAYER_FILES = [
    "F_Cu.gbr",
    "B_Cu.gbr",
    "F_Mask.gbr",
    "B_Mask.gbr",
    "F_Silkscreen.gbr",
    "B_Silkscreen.gbr",
    "Edge_Cuts.gbr",
    "drill.drl",
]


def _outline(width, height):
    corners = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]
    return [{"start": list(corners[i]), "end": list(corners[(i + 1) % 4])} for i in range(4)]


def _board_doc(extra_nodes=(), tracks=True):
    nodes = [
        {
            "id": "board",
            "type": "board",
            "props": {
                "kicad_version": "20240108",
                "generator": "test",
                "outline": _outline(30.0, 20.0),
                "design_rules": {
                    "clearance": 0.2,
                    "track_width": 0.25,
                    "via_diameter": 0.8,
                    "via_drill": 0.4,
                },
            },
        },
        {"id": "net_sig", "type": "net", "props": {"code": 1, "name": "SIG"}},
        {
            "id": "R1",
            "type": "component",
            "props": {
                "reference": "R1",
                "value": "330R",
                "footprint": "Resistor_SMD:R_0603",
                "layer": "F.Cu",
                "at": [10.0, 10.0, 0.0],
                "pads": [
                    {"number": "1", "net": "SIG", "at": [-0.8, 0.0], "size": [0.9, 1.0]},
                    {"number": "2", "net": "SIG", "at": [0.8, 0.0], "size": [0.9, 1.0]},
                ],
            },
        },
        {
            "id": "R2",
            "type": "component",
            "props": {
                "reference": "R2",
                "value": "330R",
                "footprint": "Resistor_SMD:R_0603",
                "layer": "F.Cu",
                "at": [20.0, 10.0, 0.0],
                "pads": [
                    {"number": "1", "net": "SIG", "at": [-0.8, 0.0], "size": [0.9, 1.0]},
                    {"number": "2", "net": "SIG", "at": [0.8, 0.0], "size": [0.9, 1.0]},
                ],
            },
        },
        *extra_nodes,
    ]
    if tracks:
        nodes += [
            {
                "id": "track_1",
                "type": "track",
                "props": {
                    "net": "SIG",
                    "layer": "F.Cu",
                    "start": [10.8, 10.0],
                    "end": [15.0, 10.0],
                    "width": 0.25,
                },
            },
            {
                "id": "track_2",
                "type": "track",
                "props": {
                    "net": "SIG",
                    "layer": "B.Cu",
                    "start": [15.0, 10.0],
                    "end": [19.2, 10.0],
                    "width": 0.25,
                },
            },
            {
                "id": "via_1",
                "type": "via",
                "props": {"at": [15.0, 10.0], "net": "SIG", "size": 0.8, "drill": 0.4},
            },
        ]
    return validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "gerber-test", "generator": "test"},
            "nodes": nodes,
        }
    )


def _export(document) -> zipfile.ZipFile:
    return zipfile.ZipFile(BytesIO(GerberExporter().from_ir(document)))


def _read(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode()


# --------------------------------------------------------------- file contents


def test_zip_contains_the_full_layer_set():
    archive = _export(_board_doc())
    assert archive.namelist() == _LAYER_FILES


def test_each_gerber_layer_has_valid_header_and_content():
    archive = _export(_board_doc())
    # Layers expected to carry geometry for this board (B_Mask/B_Silkscreen
    # are legitimately empty: no components sit on the back side).
    for name in ["F_Cu.gbr", "B_Cu.gbr", "F_Mask.gbr", "F_Silkscreen.gbr", "Edge_Cuts.gbr"]:
        text = _read(archive, name)
        assert "%FSLAX46Y46*%" in text, name
        assert "%MOMM*%" in text, name
        assert "%ADD10" in text, name  # at least one aperture definition
        assert "D01*" in text or "D03*" in text, name  # at least one draw/flash
        assert text.rstrip().endswith("M02*"), name
    for name in ["B_Mask.gbr", "B_Silkscreen.gbr"]:  # empty but still well-formed
        text = _read(archive, name)
        assert "%FSLAX46Y46*%" in text and text.rstrip().endswith("M02*")


def test_copper_flash_count_matches_pads_and_via():
    # Round-trip sanity: parse back the flashes on F.Cu. 4 pads + 1 via
    # annular = 5 flashes; the two F.Cu track segments contribute D01 draws.
    text = _read(_export(_board_doc()), "F_Cu.gbr")
    assert text.count("D03*") == 5
    assert text.count("D01*") == 1  # one F.Cu track segment
    # Pad aperture is a rectangle at the pad size; track aperture is round.
    assert "%ADD10R,0.900000X1.000000*%" in text
    assert "C,0.250000" in text and "C,0.800000" in text


def test_mask_openings_carry_the_standard_expansion():
    text = _read(_export(_board_doc()), "F_Mask.gbr")
    assert "R,1.000000X1.100000" in text  # 0.9x1.0 pad + 0.05mm per side
    assert text.count("D03*") == 4


def test_drill_file_has_valid_excellon_entries_per_via():
    text = _read(_export(_board_doc()), "drill.drl")
    assert text.startswith("M48")
    assert "METRIC,TZ" in text
    assert "T1C0.400" in text
    assert "X15.000Y10.000" in text
    assert text.rstrip().endswith("M30")


def test_unrouted_board_produces_completeness_warning():
    result = check_gerber_completeness(_board_doc(tracks=False))
    assert result["ready"] is True  # warnings do not block
    assert any("no routed tracks" in w for w in result["warnings"])
    routed = check_gerber_completeness(_board_doc())
    assert not any("no routed tracks" in w for w in routed["warnings"])


def test_completeness_fails_on_fab_rule_violation():
    doc = _board_doc()
    doc.nodes[0].props["design_rules"]["track_width"] = 0.05  # below JLCPCB minimum
    result = check_gerber_completeness(doc)
    assert result["ready"] is False
    assert any("trace width" in e for e in result["errors"])


# ------------------------------------------------------ real-parser validation


def _unpack(archive: zipfile.ZipFile, tmp_path: Path) -> Path:
    out = tmp_path / "gerbers"
    out.mkdir()
    archive.extractall(out)
    return out


def test_gerbonara_parses_every_layer(tmp_path):
    out = _unpack(_export(_board_doc()), tmp_path)
    from gerbonara.rs274x import GerberFile

    for name in _LAYER_FILES[:-1]:
        parsed = GerberFile.open(out / name)
        assert parsed.objects is not None
    copper = GerberFile.open(out / "F_Cu.gbr")
    assert len(copper.objects) == 6  # 5 flashes + 1 line
    from gerbonara.excellon import ExcellonFile

    drill = ExcellonFile.open(out / "drill.drl")
    assert len(drill.objects) == 1


def test_gerbonara_recognizes_the_full_layer_stack(tmp_path):
    out = _unpack(_export(_board_doc()), tmp_path)
    from gerbonara.layers import LayerStack

    stack = LayerStack.open(out)
    for side, use in [
        ("top", "copper"),
        ("bottom", "copper"),
        ("top", "mask"),
        ("top", "silk"),
        ("mechanical", "outline"),
    ]:
        assert stack[(side, use)] is not None, (side, use)
    assert len(list(stack.drill_layers)) == 1


# ------------------------------------------------------------ end-to-end (Uno)


def test_arduino_uno_place_route_export_gerbers(tmp_path, monkeypatch):
    """The canonical pipeline: build -> auto_place -> route_board -> gerbers."""
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    src = _EXAMPLES / "hardware/arduino_uno.forge.json"
    assert tools.auto_place(str(src), "placed.forge.json")["placed"]
    routed = tools.route_board("placed.forge.json", "routed.forge.json")
    assert routed["routed"] and routed["vias_used"] > 0

    result = tools.export_document(
        document_path="routed.forge.json", tool="gerber", output_path="uno_gerbers.zip"
    )
    assert result["bytes_written"] > 0
    archive = zipfile.ZipFile(tmp_path / "uno_gerbers.zip")
    assert archive.namelist() == _LAYER_FILES

    out = _unpack(archive, tmp_path)
    from gerbonara.excellon import ExcellonFile
    from gerbonara.layers import LayerStack
    from gerbonara.rs274x import GerberFile

    stack = LayerStack.open(out)
    assert stack[("top", "copper")] is not None and stack[("bottom", "copper")] is not None
    # Every via the router placed is really drilled.
    drill = ExcellonFile.open(out / "drill.drl")
    assert len(drill.objects) == routed["vias_used"]
    # Copper flash count matches pads (all components) + via annulars.
    doc = validate(json.loads((tmp_path / "routed.forge.json").read_text()))
    pad_count = sum(
        len(n.props.get("pads") or [])
        for n in doc.walk()
        if n.type == "component" and str(n.props.get("layer", "F.Cu")) != "B.Cu"
    )
    top = GerberFile.open(out / "F_Cu.gbr")
    flashes = [o for o in top.objects if type(o).__name__ == "Flash"]
    assert len(flashes) == pad_count + routed["vias_used"]

    # The completeness pre-flight is clean for a routed board.
    completeness = check_gerber_completeness(doc)
    assert completeness["ready"], completeness["errors"]


# ----------------------------------------------------- list_formats honesty


def test_list_formats_reports_stubs_honestly():
    formats = tools.list_formats()
    assert formats["gerber"] == {"import": False, "export": True}
    for stub in ("altium", "fusion360", "unreal", "blender"):
        assert formats[stub] == {"import": False, "export": False}, stub
