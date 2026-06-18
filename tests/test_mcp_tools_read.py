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
