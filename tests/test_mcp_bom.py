"""generate_bom: bill-of-materials extraction from a hardware document."""

import csv
import io
import json

import pytest

from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION


def _component(reference, value, footprint, nets):
    """A hardware component node whose pads carry the given net names."""
    return {
        "id": reference,
        "type": "component",
        "props": {
            "reference": reference,
            "value": value,
            "footprint": footprint,
            "layer": "F.Cu",
            "at": [0.0, 0.0, 0.0],
            "pads": [{"number": str(i + 1), "net": net} for i, net in enumerate(nets)],
        },
    }


def _hardware_doc(components):
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "board", "generator": "test"},
        "nodes": list(components),
    }


def _write(tmp_path, doc, name="board.forge.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# JSON output
# --------------------------------------------------------------------------- #
def test_generate_bom_json_shape(tmp_path):
    doc = _hardware_doc(
        [
            _component("R1", "10k", "R_0805", ["VCC", "GND"]),
            _component("U1", "ATmega328P", "TQFP-32", ["VCC", "GND", "D13"]),
        ]
    )
    _write(tmp_path, doc)
    out = tools.generate_bom("board.forge.json")

    assert out["total_components"] == 2
    assert out["unique_parts"] == 2
    r1 = next(e for e in out["bom"] if e["value"] == "10k")
    assert r1 == {
        "quantity": 1,
        "reference": "R1",
        "value": "10k",
        "footprint": "R_0805",
        "nets": ["VCC", "GND"],
    }


def test_generate_bom_defaults_to_json(tmp_path):
    _write(tmp_path, _hardware_doc([_component("R1", "10k", "R_0805", ["GND"])]))
    out = tools.generate_bom("board.forge.json")
    assert isinstance(out, dict)
    assert out["bom"][0]["reference"] == "R1"


# --------------------------------------------------------------------------- #
# grouping identical parts (same value + footprint)
# --------------------------------------------------------------------------- #
def test_generate_bom_groups_identical_components(tmp_path):
    doc = _hardware_doc(
        [
            _component("C1", "100nF", "C_0805", ["VCC", "GND"]),
            _component("C2", "100nF", "C_0805", ["VCC", "GND"]),
            _component("C3", "100nF", "C_0805", ["3V3", "GND"]),
            _component("C4", "100nF", "C_0805", ["VCC", "GND"]),
            # Same value, different footprint -> a distinct part.
            _component("C5", "100nF", "C_0603", ["VCC", "GND"]),
        ]
    )
    _write(tmp_path, doc)
    out = tools.generate_bom("board.forge.json")

    assert out["total_components"] == 5
    assert out["unique_parts"] == 2
    grouped = next(e for e in out["bom"] if e["footprint"] == "C_0805")
    assert grouped["quantity"] == 4
    assert grouped["reference"] == "C1,C2,C3,C4"
    # Nets are the union across the grouped components, in first-seen order.
    assert grouped["nets"] == ["VCC", "GND", "3V3"]


# --------------------------------------------------------------------------- #
# CSV output
# --------------------------------------------------------------------------- #
def test_generate_bom_csv(tmp_path):
    doc = _hardware_doc(
        [
            _component("C1", "100nF", "C_0805", ["VCC", "GND"]),
            _component("C2", "100nF", "C_0805", ["VCC", "GND"]),
            _component("R1", "10k", "R_0805", ["GND"]),
        ]
    )
    _write(tmp_path, doc)
    out = tools.generate_bom("board.forge.json", format="csv")

    assert isinstance(out, str)
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == ["Quantity", "References", "Value", "Footprint"]
    caps = next(r for r in rows[1:] if r[3] == "C_0805")
    assert caps == ["2", "C1,C2", "100nF", "C_0805"]
    # The comma-joined references survive a CSV round-trip (they were quoted).
    assert "C1,C2" in caps


# --------------------------------------------------------------------------- #
# single-component case
# --------------------------------------------------------------------------- #
def test_generate_bom_single_component(tmp_path):
    _write(tmp_path, _hardware_doc([_component("U1", "NE555", "DIP-8", ["VCC"])]))
    out = tools.generate_bom("board.forge.json")
    assert out["total_components"] == 1
    assert out["unique_parts"] == 1
    assert out["bom"][0]["quantity"] == 1
    assert out["bom"][0]["reference"] == "U1"


# --------------------------------------------------------------------------- #
# empty board (no components)
# --------------------------------------------------------------------------- #
def test_generate_bom_empty_board(tmp_path):
    doc = _hardware_doc([{"id": "net1", "type": "net", "props": {"code": 1, "name": "GND"}}])
    _write(tmp_path, doc)
    out = tools.generate_bom("board.forge.json")
    assert out == {"total_components": 0, "unique_parts": 0, "bom": []}


def test_generate_bom_empty_board_csv_has_header_only(tmp_path):
    _write(tmp_path, _hardware_doc([]))
    out = tools.generate_bom("board.forge.json", format="csv")
    assert out.strip() == "Quantity,References,Value,Footprint"


# --------------------------------------------------------------------------- #
# guard rails
# --------------------------------------------------------------------------- #
def test_generate_bom_rejects_non_hardware_document(tmp_path):
    doc = {
        "forgelab_version": SPEC_VERSION,
        "domain": "threed",
        "meta": {"name": "scene", "generator": "test"},
        "nodes": [{"id": "scene", "type": "scene", "props": {"name": "scene"}}],
    }
    _write(tmp_path, doc)
    with pytest.raises(ValueError, match="hardware"):
        tools.generate_bom("board.forge.json")


def test_generate_bom_rejects_unknown_format(tmp_path):
    _write(tmp_path, _hardware_doc([_component("R1", "10k", "R_0805", ["GND"])]))
    with pytest.raises(ValueError, match="unknown format"):
        tools.generate_bom("board.forge.json", format="xml")


def test_list_formats_includes_bom_as_export_only():
    formats = tools.list_formats()
    assert formats["bom"] == {"import": False, "export": True}
