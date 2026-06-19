import json

import pytest

from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION


def _hardware_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def test_validate_document_accepts_valid():
    assert tools.validate_document(_hardware_doc()) == {"valid": True}


def test_validate_document_reports_invalid():
    bad = _hardware_doc()
    bad["forgelab_version"] = "999.0.0"
    result = tools.validate_document(bad)
    assert result["valid"] is False
    assert "error" in result


def test_validate_document_accepts_path(tmp_path):
    # Token optimization: the agent passes a path, never loading the JSON itself.
    path = tmp_path / "doc.forge.json"
    path.write_text(json.dumps(_hardware_doc()))
    assert tools.validate_document(document_path=str(path)) == {"valid": True}


def test_validate_document_path_reports_invalid(tmp_path):
    bad = _hardware_doc()
    bad["forgelab_version"] = "999.0.0"
    path = tmp_path / "bad.forge.json"
    path.write_text(json.dumps(bad))
    result = tools.validate_document(document_path=str(path))
    assert result["valid"] is False
    assert "error" in result


def test_validate_document_missing_path_raises(tmp_path):
    with pytest.raises(ValueError, match="could not read"):
        tools.validate_document(document_path=str(tmp_path / "nope.forge.json"))


def test_validate_document_requires_a_source():
    with pytest.raises(ValueError, match="document"):
        tools.validate_document()


def test_validate_document_rejects_both_sources(tmp_path):
    path = tmp_path / "doc.forge.json"
    path.write_text(json.dumps(_hardware_doc()))
    with pytest.raises(ValueError, match="not both"):
        tools.validate_document(_hardware_doc(), document_path=str(path))


def test_load_document_returns_metadata_only(tmp_path):
    path = tmp_path / "blinky.forge.json"
    path.write_text(json.dumps(_hardware_doc()))
    meta = tools.load_document(document_path=str(path))
    assert meta["domain"] == "hardware"
    assert meta["name"] == "blinky"
    assert meta["forgelab_version"] == SPEC_VERSION
    assert meta["node_count"] == 1
    assert meta["nodes_by_type"] == {"component": 1}
    # The full document is NOT returned — that is the whole point.
    assert "nodes" not in meta


def test_load_document_counts_nested_children(tmp_path):
    doc = _hardware_doc()
    doc["nodes"] = [
        {"id": "g", "type": "group", "children": [{"id": "r1", "type": "component"}]},
        {"id": "net0", "type": "net"},
    ]
    path = tmp_path / "nested.forge.json"
    path.write_text(json.dumps(doc))
    meta = tools.load_document(document_path=str(path))
    assert meta["node_count"] == 3
    assert meta["nodes_by_type"] == {"group": 1, "component": 1, "net": 1}


def test_load_document_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="could not read"):
        tools.load_document(document_path=str(tmp_path / "nope.forge.json"))


def test_load_document_bad_json_raises(tmp_path):
    path = tmp_path / "bad.forge.json"
    path.write_text("{ not valid json")
    with pytest.raises(ValueError, match="JSON"):
        tools.load_document(document_path=str(path))


def test_load_document_resolves_bare_name_against_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    (tmp_path / "blinky.forge.json").write_text(json.dumps(_hardware_doc()))
    meta = tools.load_document(document_path="blinky.forge.json")
    assert meta["name"] == "blinky"


def test_get_domain_schema_pins_domain():
    schema = tools.get_domain_schema("hardware")
    assert schema["properties"]["domain"] == {"const": "hardware"}


def test_get_domain_schema_unknown_raises():
    with pytest.raises(ValueError, match="unknown domain"):
        tools.get_domain_schema("nope")


def test_get_prompt_returns_system_and_few_shot():
    p = tools.get_prompt("mechanical")
    assert isinstance(p["system"], str) and p["system"]
    assert "few_shot" in p


def test_list_domains():
    assert tools.list_domains() == ["hardware", "mechanical", "threed"]


def test_list_formats_reports_registered_tools():
    formats = tools.list_formats()
    assert formats["kicad"]["export"] is True
    assert formats["freecad"]["import"] is True


def _threed_doc(material_ref="mat_red"):
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "threed",
        "meta": {"name": "scene", "generator": "test"},
        "nodes": [
            {
                "id": "mat_red",
                "type": "material",
                "props": {"name": "vermilion", "base_color": [1.0, 0.0, 0.0, 1.0]},
            },
            {
                "id": "mesh_cube",
                "type": "mesh",
                "props": {
                    "name": "cube",
                    "primitives": [{"positions": [0.0, 0.0, 0.0], "material": material_ref}],
                },
            },
        ],
    }


def test_export_blender_suggests_gltf():
    with pytest.raises(ValueError, match="gltf"):
        tools.export_document(_threed_doc(), "blender")


def test_export_bad_material_ref_surfaces_id_hint():
    with pytest.raises(ValueError) as exc:
        tools.export_document(_threed_doc(material_ref="vermilion"), "gltf")
    msg = str(exc.value)
    assert "vermilion" in msg and "id" in msg


def test_generation_status_available_when_key_and_extra(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(tools, "_agent_extra_installed", lambda: True)
    status = tools.generation_status()
    assert status["available"] is True
    assert "reason" not in status


def test_generation_status_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(tools, "_agent_extra_installed", lambda: True)
    status = tools.generation_status()
    assert status["available"] is False
    assert "ANTHROPIC_API_KEY" in status["reason"]
    # Tells the agent how to proceed without generate_document.
    assert "get_domain_schema" in status["alternative"]


def test_generation_status_unavailable_without_agent_extra(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(tools, "_agent_extra_installed", lambda: False)
    status = tools.generation_status()
    assert status["available"] is False
    assert "agent extra" in status["reason"]
