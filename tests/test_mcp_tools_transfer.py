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


def _props_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [
            {
                "id": "R1",
                "type": "component",
                "props": {
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0402",
                    "layer": "F.Cu",
                    "at": [0, 0, 0],
                },
            }
        ],
    }


def test_export_writes_to_absolute_output_path(tmp_path):
    target = tmp_path / "boards" / "blinky.kicad_pcb"
    out = tools.export_document(_props_doc(), "kicad", output_path=str(target))
    assert out["tool"] == "kicad"
    assert out["path"] == str(target)
    assert "content" not in out
    data = target.read_bytes()
    assert out["bytes_written"] == len(data)
    assert b"kicad_pcb" in data


def test_export_filename_goes_into_forgelab_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    out = tools.export_document(_props_doc(), "kicad", output_path="blinky.kicad_pcb")
    assert out["path"] == str(tmp_path / "blinky.kicad_pcb")
    assert (tmp_path / "blinky.kicad_pcb").exists()


def test_export_filename_defaults_to_cwd_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGELAB_OUTPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    out = tools.export_document(_props_doc(), "kicad", output_path="blinky.kicad_pcb")
    assert out["path"] == str(tmp_path / "blinky.kicad_pcb")
    assert (tmp_path / "blinky.kicad_pcb").exists()


def test_export_relative_path_with_directory_ignores_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.chdir(tmp_path)
    out = tools.export_document(_props_doc(), "kicad", output_path="sub/blinky.kicad_pcb")
    assert out["path"] == "sub/blinky.kicad_pcb"
    assert (tmp_path / "sub" / "blinky.kicad_pcb").exists()


def test_export_without_output_path_is_unchanged():
    out = tools.export_document(_props_doc(), "kicad")
    assert set(out) == {"tool", "encoding", "content"}


def test_export_accepts_document_path(tmp_path):
    path = tmp_path / "blinky.forge.json"
    path.write_text(json.dumps(_props_doc()))
    out = tools.export_document(document_path=str(path), tool="kicad")
    assert out["tool"] == "kicad"
    assert "kicad_pcb" in out["content"]


def test_export_document_path_to_output_path(tmp_path):
    # The full token-optimized chain: path in, path out, no inline JSON anywhere.
    src = tmp_path / "blinky.forge.json"
    src.write_text(json.dumps(_props_doc()))
    target = tmp_path / "blinky.kicad_pcb"
    out = tools.export_document(document_path=str(src), tool="kicad", output_path=str(target))
    assert out["path"] == str(target)
    assert "content" not in out
    assert b"kicad_pcb" in target.read_bytes()


def test_export_missing_document_path_raises(tmp_path):
    with pytest.raises(ValueError, match="could not read"):
        tools.export_document(document_path=str(tmp_path / "nope.forge.json"), tool="kicad")


def test_export_requires_a_document_source():
    with pytest.raises(ValueError, match="document"):
        tools.export_document(tool="kicad")


def test_export_rejects_both_document_and_path(tmp_path):
    path = tmp_path / "blinky.forge.json"
    path.write_text(json.dumps(_props_doc()))
    with pytest.raises(ValueError, match="not both"):
        tools.export_document(_props_doc(), "kicad", document_path=str(path))
