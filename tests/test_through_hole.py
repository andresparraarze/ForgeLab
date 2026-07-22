"""Through-hole / drill support: the Pad ``drill`` field and its two exporters.

A pad with a ``drill`` is a through-hole pad (plated barrel spanning every
copper layer); a pad without one is SMD, exactly as before — this file pins
both the new through-hole grammar (verified against real KiCad 10 footprints)
and the fact that the SMD path is byte-for-byte unchanged.
"""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from forgelab.components.library import get_component
from forgelab.core import validate
from forgelab.exporters.hardware.gerber import GerberExporter
from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.formats import parse
from forgelab.spec import SPEC_VERSION, Drill, ForgeDocument, Node, Pad
from forgelab.validation import check_fab_rules

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

# The SMD KiCad export must never change when the drill field is absent. This is
# the SHA-256 of the all-SMD blinky export — the byte-identity guard, the same
# proof the glTF alphaMode fix used for its opaque path.
_BLINKY_SMD_SHA = "ede579923aed96af83ef573444585e71081bce2f18acc994181557c3d7d97857"


def _doc(pads: list[dict], layer: str = "F.Cu") -> ForgeDocument:
    outline = [
        {"start": [0, 0], "end": [30, 0]},
        {"start": [30, 0], "end": [30, 20]},
        {"start": [30, 20], "end": [0, 20]},
        {"start": [0, 20], "end": [0, 0]},
    ]
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "tht", "generator": "test"},
            "nodes": [
                {
                    "id": "board",
                    "type": "board",
                    "props": {
                        "kicad_version": "20240108",
                        "generator": "test",
                        "outline": outline,
                        "design_rules": {
                            "clearance": 0.2,
                            "track_width": 0.25,
                            "via_diameter": 0.8,
                            "via_drill": 0.4,
                        },
                    },
                },
                {"id": "net_GND", "type": "net", "props": {"code": 1, "name": "GND"}},
                {
                    "id": "J1",
                    "type": "component",
                    "props": {
                        "reference": "J1",
                        "value": "Conn",
                        "footprint": "Test:Header",
                        "layer": layer,
                        "at": [15, 10, 0],
                        "pads": pads,
                    },
                },
            ],
        }
    )


def _pads(tree, footprint_index: int = 0):
    footprints = [e for e in tree if isinstance(e, list) and e and str(e[0]) == "footprint"]
    fp = footprints[footprint_index]
    return [e for e in fp if isinstance(e, list) and str(e[0]) == "pad"]


def _tokens(pad) -> dict:
    return {str(e[0]): e for e in pad if isinstance(e, list) and e}


# ------------------------------------------------------------------ Drill model


def test_round_and_oval_drills_validate():
    assert Drill(diameter=1.0).diameter == 1.0
    assert Drill(oval=[1.3, 0.5]).oval == [1.3, 0.5]
    assert Drill(diameter=0.9).plated is True


def test_drill_requires_exactly_one_shape():
    with pytest.raises(ValidationError):
        Drill()  # neither diameter nor oval
    with pytest.raises(ValidationError):
        Drill(diameter=1.0, oval=[1.3, 0.5])  # both


def test_drill_oval_must_be_width_height():
    with pytest.raises(ValidationError):
        Drill(oval=[1.0])


def test_pad_without_drill_is_smd():
    assert Pad(number="1", net="GND").drill is None


# ------------------------------------------------------- KiCad through-hole grammar


def test_through_hole_pad_exports_verified_kicad_grammar():
    doc = _doc([{"number": "1", "net": "GND", "at": [0, 0], "size": [1.7, 1.7], "shape": "rect",
                 "drill": {"diameter": 1.0}}])  # fmt: skip
    tree = parse(KiCadExporter().from_ir(doc).decode())
    (pad,) = _pads(tree)
    assert str(pad[2]) == "thru_hole"  # plated through-hole
    tok = _tokens(pad)
    assert tok["drill"][1] == 1  # round (drill 1)
    # copper + mask span every layer — what lets a pour/back-side track connect
    assert [str(x) for x in tok["layers"][1:]] == ["*.Cu", "*.Mask"]
    assert str(tok["remove_unused_layers"][1]) == "no"


def test_non_plated_pad_exports_np_thru_hole():
    doc = _doc([{"number": "1", "net": "", "at": [0, 0], "shape": "circle",
                 "drill": {"diameter": 3.2, "plated": False}}])  # fmt: skip
    (pad,) = _pads(parse(KiCadExporter().from_ir(doc).decode()))
    assert str(pad[2]) == "np_thru_hole"


def test_oval_drill_exports_oval_token():
    doc = _doc([{"number": "1", "net": "GND", "at": [0, 0], "size": [1.9, 1.4], "shape": "oval",
                 "drill": {"oval": [1.3, 0.5]}}])  # fmt: skip
    (pad,) = _pads(parse(KiCadExporter().from_ir(doc).decode()))
    drill = _tokens(pad)["drill"]
    assert str(drill[1]) == "oval" and drill[2] == 1.3 and drill[3] == 0.5


# ----------------------------------------------------------- SMD path unchanged


def test_smd_export_is_byte_identical():
    doc = ForgeDocument.model_validate(
        json.loads((_EXAMPLES / "hardware/blinky.forge.json").read_text())
    )
    assert hashlib.sha256(KiCadExporter().from_ir(doc)).hexdigest() == _BLINKY_SMD_SHA


def test_smd_pad_keeps_single_layer_and_no_drill_tokens():
    doc = _doc([{"number": "1", "net": "GND", "at": [0, 0], "size": [1.6, 1.6]}])
    text = KiCadExporter().from_ir(doc).decode()
    (pad,) = _pads(parse(text))
    assert str(pad[2]) == "smd"
    assert [str(x) for x in _tokens(pad)["layers"][1:]] == ["F.Cu"]
    assert "drill" not in _tokens(pad)
    assert "thru_hole" not in text


# ------------------------------------------------------------- Gerber / Excellon


def _drill_file(doc: ForgeDocument) -> str:
    data = GerberExporter().from_ir(doc)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read("drill.drl").decode()


def _with_via(doc: ForgeDocument) -> ForgeDocument:
    doc.nodes.append(
        Node(id="via1", type="via", props={"at": [5, 5], "net": "GND", "size": 0.8, "drill": 0.4})
    )
    return doc


def test_drill_file_groups_via_and_pad_holes_by_diameter():
    # Two round through-hole pads (1.0mm) plus a via (0.4mm).
    doc = _with_via(
        _doc(
            [
                {"number": "1", "net": "GND", "at": [-1, 0], "drill": {"diameter": 1.0}},
                {"number": "2", "net": "GND", "at": [1, 0], "drill": {"diameter": 1.0}},
            ]
        )
    )
    text = _drill_file(doc)
    # One tool per distinct diameter; both 1.0mm pad holes share a tool.
    assert "C1.000" in text and "C0.400" in text
    assert text.count("G85") == 0  # round holes are flashed points, not slots
    # Three drilled points total: two pad holes + one via.
    body = text.split("%", 1)[1]
    assert body.count("X") - body.count("G85") == 3


def test_oval_drill_becomes_excellon_slot():
    doc = _doc([{"number": "1", "net": "GND", "at": [0, 0], "size": [1.9, 1.4],
                 "drill": {"oval": [1.3, 0.5]}}])  # fmt: skip
    text = _drill_file(doc)
    assert "G85" in text  # a routed slot
    assert "C0.500" in text  # tool = the slot's narrow dimension


def test_gerbonara_parses_extended_drill_with_correct_hole_count(tmp_path):
    pytest.importorskip("gerbonara", reason="gerbonara (dev dep) not installed")
    from gerbonara.excellon import ExcellonFile

    doc = _with_via(
        _doc(
            [
                {"number": "1", "net": "GND", "at": [-1, 0], "drill": {"diameter": 1.0}},
                {"number": "2", "net": "GND", "at": [1, 0], "drill": {"diameter": 1.0}},
            ]
        )
    )
    drl = tmp_path / "drill.drl"
    drl.write_text(_drill_file(doc))
    parsed = ExcellonFile.open(drl)
    # 2 through-hole pad holes + 1 via = 3 holes, cleanly parsed.
    assert len(parsed.objects) == 3


# --------------------------------------------------------------- fab + library


def test_check_fabrication_catches_undersized_drill():
    # jlcpcb minimum drill size is 0.2mm; a 0.1mm hole is unmanufacturable.
    doc = _doc([{"number": "1", "net": "GND", "at": [0, 0], "drill": {"diameter": 0.1}}])
    result = check_fab_rules(doc)
    assert result["passed"] is False
    assert any("drill" in e and "0.1" in e for e in result["errors"])


def test_library_through_hole_parts_validate_and_carry_drills():
    nodes: list[dict] = [
        {
            "id": "board",
            "type": "board",
            "props": {
                "kicad_version": "20240108",
                "generator": "test",
                "outline": [
                    {"start": [0, 0], "end": [50, 0]},
                    {"start": [50, 0], "end": [50, 40]},
                    {"start": [50, 40], "end": [0, 40]},
                    {"start": [0, 40], "end": [0, 0]},
                ],
                "design_rules": {
                    "clearance": 0.2,
                    "track_width": 0.25,
                    "via_diameter": 0.8,
                    "via_drill": 0.4,
                },
            },
        }
    ]
    for i, name in enumerate(("PinHeader-1x6", "PinHeader-2x3-ICSP", "JST-PH-2")):
        defn = get_component(name)
        # Every pad of a genuinely-through-hole part carries a drill.
        assert all(p.get("drill") for p in defn["pads"]), name
        nodes.append(
            {
                "id": f"J{i}",
                "type": "component",
                "props": {
                    "reference": f"J{i}",
                    "value": defn["value"],
                    "footprint": defn["footprint"],
                    "layer": "F.Cu",
                    "at": [10 + i * 12, 20, 0],
                    "pads": defn["pads"],
                },
            }
        )
    doc = {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "lib", "generator": "test"},
        "nodes": nodes,
    }
    # validate() raises on an invalid document; a clean return is the assertion.
    validated = validate(doc)
    assert validated.domain.value == "hardware"
