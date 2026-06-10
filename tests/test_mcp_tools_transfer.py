import json
from pathlib import Path

import pytest

from forgelab.core import Registry, validate
from forgelab.exporters.base import Exporter
from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION, ForgeDocument

_EXAMPLE = Path("examples/mechanical/box-with-hole.forge.json")


def _hardware_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [
            {
                "id": "r1",
                "type": "component",
                "props": {
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0402",
                    "layer": "F.Cu",
                    "at": [0.0, 0.0, 0.0],
                },
            }
        ],
    }


def test_export_hardware_is_utf8_text():
    out = tools.export_document(_hardware_doc(), "kicad")
    assert out["tool"] == "kicad"
    assert out["encoding"] == "utf-8"
    assert "kicad_pcb" in out["content"]


def test_freecad_round_trip_via_base64():
    doc = json.loads(_EXAMPLE.read_text())
    out = tools.export_document(doc, "freecad")
    assert out["encoding"] == "base64"
    back = tools.import_file("freecad", out["content"], out["encoding"])
    assert back == validate(doc).model_dump(mode="json")


def test_export_unknown_tool_raises():
    with pytest.raises(ValueError, match="No exporter registered"):
        tools.export_document(_hardware_doc(), "nope")


def test_import_unknown_tool_raises():
    with pytest.raises(ValueError, match="No importer registered"):
        tools.import_file("nope", "data", "utf-8")


def test_export_not_implemented_is_clear(monkeypatch):
    class Stub(Exporter):
        tool_name = "stub"

        def from_ir(self, document: ForgeDocument) -> bytes:
            raise NotImplementedError("stub exporter")

    reg = Registry()
    reg.register_exporter(Stub)
    monkeypatch.setattr(tools, "_registry", reg)
    with pytest.raises(ValueError, match="not implemented"):
        tools.export_document(_hardware_doc(), "stub")


def test_export_invalid_document_is_clear():
    bad = _hardware_doc()
    bad["forgelab_version"] = "999.0.0"
    with pytest.raises(ValueError, match="invalid document"):
        tools.export_document(bad, "kicad")


def test_import_malformed_base64_is_clear():
    with pytest.raises(ValueError, match="invalid base64"):
        tools.import_file("freecad", "not!valid!base64!", "base64")


def test_export_exporter_invalid_props_is_clear():
    # Structurally valid IR (lenient validator) but propless component
    # (strict exporter) must surface the module's clear ValueError.
    doc = {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "x", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }
    with pytest.raises(ValueError, match="export failed for 'kicad'"):
        tools.export_document(doc, "kicad")
