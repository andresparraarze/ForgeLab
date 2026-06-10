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
