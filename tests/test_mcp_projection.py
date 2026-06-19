import json

import pytest

from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION


def _hardware_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [
            {
                "id": "board",
                "type": "board",
                "props": {
                    "kicad_version": "20240108",
                    "generator": "test",
                    "layers": [],
                    "outline": [],
                    "design_rules": {
                        "clearance": 0.2,
                        "track_width": 0.25,
                        "via_diameter": 0.8,
                        "via_drill": 0.4,
                    },
                },
            },
            {"id": "net:1", "type": "net", "props": {"code": 1, "name": "GND"}},
            {
                "id": "R1",
                "type": "component",
                "props": {
                    "reference": "R1",
                    "value": "330R",
                    "footprint": "Resistor_SMD:R_0402",
                    "layer": "F.Cu",
                    "at": [0.0, 0.0, 0.0],
                    "pads": [{"number": "1", "net": "GND", "at": [-1.0, 0.0]}],
                },
            },
        ],
    }


def _write(path, doc):
    path.write_text(json.dumps(doc))
    return path


# --------------------------------------------------------------------------- #
# load_document projection
# --------------------------------------------------------------------------- #
def test_load_document_no_projection_is_unchanged(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    out = tools.load_document(document_path=str(src))
    assert set(out) == {"domain", "name", "forgelab_version", "node_count", "nodes_by_type"}


def test_load_document_metadata_projection(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    out = tools.load_document(document_path=str(src), projection="metadata")
    assert "nodes" not in out
    assert out["nodes_by_type"] == {"board": 1, "net": 1, "component": 1}


def test_load_document_topology_projection_strips_pad_coords(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    out = tools.load_document(document_path=str(src), projection="topology")
    comp = next(n for n in out["nodes"] if n["type"] == "component")
    assert "at" not in comp["props"]["pads"][0]


def test_load_document_geometry_projection_strips_board(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    out = tools.load_document(document_path=str(src), projection="geometry")
    assert "board" not in {n["type"] for n in out["nodes"]}


def test_load_document_unknown_projection_raises(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    with pytest.raises(ValueError, match="projection"):
        tools.load_document(document_path=str(src), projection="bogus")


# --------------------------------------------------------------------------- #
# validate_document projection
# --------------------------------------------------------------------------- #
def test_validate_document_with_projection_returns_view(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    out = tools.validate_document(document_path=str(src), projection="metadata")
    assert out["valid"] is True
    assert out["projection"]["nodes_by_type"] == {"board": 1, "net": 1, "component": 1}


def test_validate_document_without_projection_is_unchanged(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    assert tools.validate_document(document_path=str(src)) == {"valid": True}


def test_validate_document_invalid_with_projection_reports_error(tmp_path):
    bad = _hardware_doc()
    bad["forgelab_version"] = "999.0.0"
    src = _write(tmp_path / "b.forge.json", bad)
    out = tools.validate_document(document_path=str(src), projection="metadata")
    assert out["valid"] is False
    assert "projection" not in out


# --------------------------------------------------------------------------- #
# export_document projection twist
# --------------------------------------------------------------------------- #
def test_export_with_topology_projection_writes_file_returns_lightweight(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    target = tmp_path / "b.kicad_pcb"
    out = tools.export_document(
        document_path=str(src),
        tool="kicad",
        output_path=str(target),
        projection="topology",
    )
    # The export still happened: a real KiCad file is on disk.
    assert b"kicad_pcb" in target.read_bytes()
    # But the response is lightweight: no export bytes, just the projection.
    assert out["tool"] == "kicad"
    assert out["exported"] is True
    assert out["path"] == str(target)
    assert "content" not in out
    assert "nodes" in out["projection"]
    comp = next(n for n in out["projection"]["nodes"] if n["type"] == "component")
    assert "at" not in comp["props"]["pads"][0]  # topology strips pad coords


def test_export_with_projection_no_output_path_still_exports(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    out = tools.export_document(document_path=str(src), tool="kicad", projection="topology")
    assert out["exported"] is True
    assert "content" not in out  # bytes discarded
    assert out["projection"]["nodes_by_type"] == {"board": 1, "net": 1, "component": 1}


def test_export_without_projection_unchanged(tmp_path):
    src = _write(tmp_path / "b.forge.json", _hardware_doc())
    out = tools.export_document(document_path=str(src), tool="kicad")
    assert set(out) == {"tool", "encoding", "content"}


# --------------------------------------------------------------------------- #
# get_projection_schema
# --------------------------------------------------------------------------- #
def test_get_projection_schema_tool():
    out = tools.get_projection_schema("threed", "geometry")
    assert out["domain"] == "threed"
    assert out["projection"] == "geometry"
    assert out["includes"] and out["excludes"]


def test_get_projection_schema_unknown_raises():
    with pytest.raises(ValueError):
        tools.get_projection_schema("nope", "metadata")
