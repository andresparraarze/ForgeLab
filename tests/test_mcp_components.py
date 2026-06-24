"""Component library: list_components / get_component MCP tools and the geometry
they hand back, including dropping a definition into a valid hardware document."""

import pytest

from forgelab.calc import calculate_pad_positions
from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION

_CATEGORIES = {"Microcontrollers", "Regulators", "USB", "Passives", "Connectors"}


def _all_names():
    return [name for names in tools.list_components().values() for name in names]


def _doc_with(component):
    """A minimal hardware document placing one library component."""
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "test", "generator": "test"},
        "nodes": [
            {
                "id": "U1",
                "type": "component",
                "props": {
                    "reference": "U1",
                    "value": component["value"],
                    "footprint": component["footprint"],
                    "layer": "F.Cu",
                    "at": [10.0, 10.0, 0.0],
                    "pads": component["pads"],
                },
            }
        ],
    }


# --------------------------------------------------------------------------- #
# list_components
# --------------------------------------------------------------------------- #
def test_list_components_returns_all_categories():
    grouped = tools.list_components()
    assert set(grouped) == _CATEGORIES
    # The brief asks for at least 20 components; we ship more.
    assert sum(len(names) for names in grouped.values()) >= 20


def test_list_components_includes_the_named_parts():
    grouped = tools.list_components()
    assert {"ESP32-WROOM-32", "ATmega328P", "ATmega2560"} <= set(grouped["Microcontrollers"])
    assert {"AMS1117-3.3", "AMS1117-5.0", "LM7805", "MCP1700-3302"} <= set(grouped["Regulators"])
    assert {"CH340G", "CP2102", "USB-B", "USB-C-16P"} <= set(grouped["USB"])
    # 2.54mm pin headers 1x2 .. 1x10.
    for n in range(2, 11):
        assert f"PinHeader-1x{n}" in grouped["Connectors"]
    assert {"PinHeader-2x3-ICSP", "JST-PH-2"} <= set(grouped["Connectors"])


# --------------------------------------------------------------------------- #
# get_component
# --------------------------------------------------------------------------- #
def test_get_component_returns_full_definition():
    part = tools.get_component("AMS1117-3.3")
    assert part["name"] == "AMS1117-3.3"
    assert part["category"] == "Regulators"
    assert part["footprint"] == "Package_TO_SOT_SMD:SOT-223-3_TabPin2"
    assert part["description"]
    assert part["pads"] and all("number" in p and "at" in p for p in part["pads"])


def test_get_component_returns_valid_pad_geometry():
    for name in _all_names():
        part = tools.get_component(name)
        pads = part["pads"]
        assert pads, f"{name} has no pads"
        numbers = [p["number"] for p in pads]
        assert len(numbers) == len(set(numbers)), f"{name} has duplicate pad numbers"
        for pad in pads:
            at = pad["at"]
            assert isinstance(at, list) and len(at) == 2
            assert all(isinstance(coord, (int, float)) for coord in at)


def test_get_component_tqfp_matches_calculate_pad_positions():
    # The TQFP microcontrollers must use the same deterministic geometry the
    # calculate_pad_positions tool produces.
    atmega328 = tools.get_component("ATmega328P")
    expected_328 = [
        {"number": p["number"], "at": p["at"]} for p in calculate_pad_positions("QFP", 0.8, 32)
    ]
    assert atmega328["pads"] == expected_328

    atmega2560 = tools.get_component("ATmega2560")
    expected_2560 = [
        {"number": p["number"], "at": p["at"]} for p in calculate_pad_positions("QFP", 0.5, 100)
    ]
    assert atmega2560["pads"] == expected_2560
    assert len(atmega2560["pads"]) == 100


def test_get_component_is_case_insensitive():
    assert tools.get_component("atmega328p")["name"] == "ATmega328P"


def test_get_component_unknown_name_lists_options():
    with pytest.raises(ValueError, match="unknown component"):
        tools.get_component("NotARealPart")


def test_esp32_has_eighteen_pads_per_side():
    pads = tools.get_component("ESP32-WROOM-32")["pads"]
    assert len(pads) == 36  # 18 per long edge


# --------------------------------------------------------------------------- #
# a dropped-in component validates
# --------------------------------------------------------------------------- #
def test_component_dropped_into_document_validates():
    component = tools.get_component("ATmega328P")
    result = tools.validate_document(document=_doc_with(component))
    assert result == {"valid": True}


def test_every_component_validates_when_placed():
    for name in _all_names():
        component = tools.get_component(name)
        result = tools.validate_document(document=_doc_with(component))
        assert result["valid"] is True, f"{name} failed: {result.get('error')}"
