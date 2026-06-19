import json

import pytest

from forgelab.mcp import tools
from forgelab.patch import apply_patch
from forgelab.spec import SPEC_VERSION


def _doc():
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
                    "value": "330R",
                    "footprint": "Resistor_SMD:R_0402",
                    "layer": "F.Cu",
                    "at": [0.0, 0.0, 0.0],
                },
            }
        ],
    }


def _write(path, doc):
    path.write_text(json.dumps(doc))
    return path


def _read(path):
    return json.loads(path.read_text())


# --------------------------------------------------------------------------- #
# patch_document
# --------------------------------------------------------------------------- #
def test_patch_document_replace_in_place(tmp_path):
    src = _write(tmp_path / "blinky.forge.json", _doc())
    result = tools.patch_document(
        document_path=str(src),
        patch=[{"op": "replace", "path": "/nodes/0/props/value", "value": "10k"}],
    )
    assert result == {
        "patched": True,
        "document_path": str(src),
        "nodes_changed": 1,
        "valid": True,
    }
    assert _read(src)["nodes"][0]["props"]["value"] == "10k"


def test_patch_document_add_component(tmp_path):
    src = _write(tmp_path / "blinky.forge.json", _doc())
    new_node = {
        "id": "R2",
        "type": "component",
        "props": {
            "reference": "R2",
            "value": "1k",
            "footprint": "Resistor_SMD:R_0402",
            "layer": "F.Cu",
            "at": [5.0, 0.0, 0.0],
        },
    }
    result = tools.patch_document(
        document_path=str(src),
        patch=[{"op": "add", "path": "/nodes/-", "value": new_node}],
    )
    assert result["nodes_changed"] == 1
    assert [n["id"] for n in _read(src)["nodes"]] == ["R1", "R2"]


def test_patch_document_output_path_leaves_source_untouched(tmp_path):
    src = _write(tmp_path / "blinky.forge.json", _doc())
    out = tmp_path / "blinky-v2.forge.json"
    result = tools.patch_document(
        document_path=str(src),
        patch=[{"op": "replace", "path": "/nodes/0/props/value", "value": "10k"}],
        output_path=str(out),
    )
    assert result["document_path"] == str(out)
    assert _read(src)["nodes"][0]["props"]["value"] == "330R"  # source unchanged
    assert _read(out)["nodes"][0]["props"]["value"] == "10k"  # written to output


def test_patch_document_validate_rejects_invalid_without_writing(tmp_path):
    src = _write(tmp_path / "blinky.forge.json", _doc())
    result = tools.patch_document(
        document_path=str(src),
        patch=[{"op": "replace", "path": "/forgelab_version", "value": "999.0.0"}],
    )
    assert result["patched"] is False
    assert result["valid"] is False
    assert "error" in result
    assert result["nodes_changed"] == 0  # touched metadata, not nodes
    assert _read(src)["forgelab_version"] == SPEC_VERSION  # file not modified


def test_patch_document_validate_false_writes_without_checking(tmp_path):
    src = _write(tmp_path / "blinky.forge.json", _doc())
    result = tools.patch_document(
        document_path=str(src),
        patch=[{"op": "replace", "path": "/forgelab_version", "value": "999.0.0"}],
        validate=False,
    )
    assert result["patched"] is True
    assert result["valid"] is None
    assert _read(src)["forgelab_version"] == "999.0.0"  # written despite being invalid


def test_patch_document_counts_only_node_operations(tmp_path):
    src = _write(tmp_path / "blinky.forge.json", _doc())
    result = tools.patch_document(
        document_path=str(src),
        patch=[
            {"op": "replace", "path": "/meta/name", "value": "renamed"},
            {"op": "replace", "path": "/nodes/0/props/value", "value": "10k"},
        ],
    )
    assert result["nodes_changed"] == 1


def test_patch_document_bad_patch_raises(tmp_path):
    src = _write(tmp_path / "blinky.forge.json", _doc())
    with pytest.raises(ValueError, match="patch failed"):
        tools.patch_document(
            document_path=str(src),
            patch=[{"op": "remove", "path": "/nodes/99"}],
        )


# --------------------------------------------------------------------------- #
# diff_documents
# --------------------------------------------------------------------------- #
def test_diff_documents_roundtrip(tmp_path):
    doc_a = _doc()
    doc_b = _doc()
    doc_b["nodes"][0]["props"]["value"] = "10k"
    doc_b["nodes"].append({"id": "R2", "type": "component"})
    a = _write(tmp_path / "a.forge.json", doc_a)
    b = _write(tmp_path / "b.forge.json", doc_b)

    patch = tools.diff_documents(document_path_a=str(a), document_path_b=str(b))
    assert isinstance(patch, list) and patch
    # Applying the diff to A reproduces B exactly.
    assert apply_patch(_read(a), patch) == _read(b)


def test_diff_documents_identical_is_empty(tmp_path):
    a = _write(tmp_path / "a.forge.json", _doc())
    b = _write(tmp_path / "b.forge.json", _doc())
    assert tools.diff_documents(document_path_a=str(a), document_path_b=str(b)) == []
