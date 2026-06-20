"""verify_sync: native-file ⇄ document hash checks + patch guard behavior."""

import json

import pytest

from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION
from forgelab.sync import HASH_KEY, read_native_hash


def _hardware_doc():
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


def _threed_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "threed",
        "meta": {"name": "cube", "generator": "test"},
        "nodes": [
            {
                "id": "scene",
                "type": "scene",
                "props": {"name": "scene"},
            }
        ],
    }


def _mechanical_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "mechanical",
        "meta": {"name": "box", "generator": "test", "description": None},
        "nodes": [
            {"id": "Part", "type": "part", "props": {"name": "Part"}},
            {"id": "Body", "type": "body", "props": {"name": "Body", "part": "Part"}},
        ],
    }


def _write(tmp_path, name, doc):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# hashes embedded on export are readable per format
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("doc_fn", "tool", "native_name"),
    [
        (_hardware_doc, "kicad", "blinky.kicad_pcb"),
        (_threed_doc, "gltf", "cube.gltf"),
        (_mechanical_doc, "freecad", "box.FCStd"),
    ],
)
def test_export_embeds_a_readable_hash(tmp_path, doc_fn, tool, native_name):
    doc_path = _write(tmp_path, "d.forge.json", doc_fn())
    native = tmp_path / native_name
    tools.export_document(document_path=str(doc_path), tool=tool, output_path=str(native))
    embedded = read_native_hash(tool, native.read_bytes())
    assert embedded is not None and len(embedded) == 64


# --------------------------------------------------------------------------- #
# in-sync / out-of-sync detection
# --------------------------------------------------------------------------- #
def test_verify_sync_reports_in_sync(tmp_path):
    doc_path = _write(tmp_path, "d.forge.json", _hardware_doc())
    native = tmp_path / "blinky.kicad_pcb"
    tools.export_document(document_path=str(doc_path), tool="kicad", output_path=str(native))

    out = tools.verify_sync(str(doc_path), str(native))
    assert out["in_sync"] is True
    assert out["document_hash"] == out["native_hash"]
    assert "recommendation" not in out


def test_verify_sync_detects_native_modification(tmp_path):
    doc_path = _write(tmp_path, "d.forge.json", _hardware_doc())
    native = tmp_path / "blinky.kicad_pcb"
    tools.export_document(document_path=str(doc_path), tool="kicad", output_path=str(native))

    # Simulate the native file being modified out from under the document: its
    # embedded hash no longer matches what the .forge.json hashes to.
    tampered = native.read_text(encoding="utf-8").replace(
        f'(property "{HASH_KEY}" "', f'(property "{HASH_KEY}" "deadbeef'
    )
    native.write_text(tampered, encoding="utf-8")

    out = tools.verify_sync(str(doc_path), str(native))
    assert out["in_sync"] is False
    assert out["native_hash"] != out["document_hash"]
    assert "import_file" in out["recommendation"]


def test_verify_sync_native_without_hash_is_out_of_sync(tmp_path):
    doc_path = _write(tmp_path, "d.forge.json", _hardware_doc())
    native = tmp_path / "blinky.kicad_pcb"
    native.write_text("(kicad_pcb (version 20221018))\n", encoding="utf-8")

    out = tools.verify_sync(str(doc_path), str(native))
    assert out["in_sync"] is False
    assert out["native_hash"] is None


def test_verify_sync_unknown_extension_raises(tmp_path):
    doc_path = _write(tmp_path, "d.forge.json", _hardware_doc())
    native = tmp_path / "blinky.unknown"
    native.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="determine the format tool"):
        tools.verify_sync(str(doc_path), str(native))


# --------------------------------------------------------------------------- #
# patch_document guard + force override
# --------------------------------------------------------------------------- #
def _out_of_sync_setup(tmp_path):
    doc_path = _write(tmp_path, "d.forge.json", _hardware_doc())
    native = tmp_path / "blinky.kicad_pcb"
    tools.export_document(document_path=str(doc_path), tool="kicad", output_path=str(native))
    tampered = native.read_text(encoding="utf-8").replace(
        f'(property "{HASH_KEY}" "', f'(property "{HASH_KEY}" "deadbeef'
    )
    native.write_text(tampered, encoding="utf-8")
    return doc_path, native


_PATCH = [{"op": "replace", "path": "/nodes/0/props/value", "value": "22k"}]


def test_patch_refuses_when_native_out_of_sync(tmp_path):
    doc_path, native = _out_of_sync_setup(tmp_path)
    out = tools.patch_document(str(doc_path), _PATCH, native_path=str(native))
    assert out["patched"] is False
    assert out["in_sync"] is False
    assert "out of sync" in out["error"]
    # Nothing was written: the value is unchanged on disk.
    assert json.loads(doc_path.read_text())["nodes"][0]["props"]["value"] == "10k"


def test_patch_force_overrides_sync_guard(tmp_path):
    doc_path, native = _out_of_sync_setup(tmp_path)
    out = tools.patch_document(str(doc_path), _PATCH, native_path=str(native), force=True)
    assert out["patched"] is True
    assert json.loads(doc_path.read_text())["nodes"][0]["props"]["value"] == "22k"


def test_patch_proceeds_when_in_sync(tmp_path):
    doc_path = _write(tmp_path, "d.forge.json", _hardware_doc())
    native = tmp_path / "blinky.kicad_pcb"
    tools.export_document(document_path=str(doc_path), tool="kicad", output_path=str(native))

    out = tools.patch_document(str(doc_path), _PATCH, native_path=str(native))
    assert out["patched"] is True
    assert json.loads(doc_path.read_text())["nodes"][0]["props"]["value"] == "22k"


def test_patch_without_native_path_is_unguarded(tmp_path):
    doc_path = _write(tmp_path, "d.forge.json", _hardware_doc())
    out = tools.patch_document(str(doc_path), _PATCH)
    assert out["patched"] is True
