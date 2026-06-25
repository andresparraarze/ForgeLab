"""Hardware-domain engineering rule checks (forgelab.validation.hardware)."""

from forgelab.core import validate
from forgelab.mcp import tools
from forgelab.spec.version import SPEC_VERSION
from forgelab.validation import check_hardware


def _doc(nodes, domain="hardware"):
    return validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": domain,
            "meta": {"name": "t", "generator": "test", "description": None},
            "nodes": nodes,
        }
    )


def _net(name, code):
    return {"id": f"net{code}", "type": "net", "props": {"code": code, "name": name}}


def _board(outline):
    return {
        "id": "board",
        "type": "board",
        "props": {
            "kicad_version": "20221018",
            "generator": "forgelab",
            "design_rules": {
                "clearance": 0.2,
                "track_width": 0.25,
                "via_diameter": 0.8,
                "via_drill": 0.4,
            },
            "outline": outline,
        },
    }


def _rect_outline():
    return [
        {"start": [0.0, 0.0], "end": [10.0, 0.0]},
        {"start": [10.0, 0.0], "end": [10.0, 10.0]},
        {"start": [10.0, 10.0], "end": [0.0, 10.0]},
        {"start": [0.0, 10.0], "end": [0.0, 0.0]},
    ]


def _component(ref, value, footprint, nets):
    return {
        "id": ref,
        "type": "component",
        "props": {
            "reference": ref,
            "value": value,
            "footprint": footprint,
            "layer": "F.Cu",
            "at": [1.0, 1.0, 0.0],
            "pads": [{"number": str(i + 1), "net": n} for i, n in enumerate(nets)],
        },
    }


def _errors_warnings(nodes, domain="hardware"):
    return check_hardware(_doc(nodes, domain))


# --------------------------------------------------------------------------- #
# domain gating
# --------------------------------------------------------------------------- #
def test_non_hardware_document_returns_empty():
    threed = _doc([{"id": "s", "type": "scene", "props": {"name": "s"}}], domain="threed")
    assert check_hardware(threed) == ([], [])


# --------------------------------------------------------------------------- #
# 1. LED current-limiting resistor
# --------------------------------------------------------------------------- #
def test_led_without_resistor_warns():
    nodes = [
        _board(_rect_outline()),
        _net("VCC", 1),
        _net("GND", 2),
        _component("D1", "LED red", "LED_SMD:LED_0805_2012Metric", ["VCC", "GND"]),
    ]
    _errors, warnings = _errors_warnings(nodes)
    assert any("LED D1 on net VCC has no current-limiting resistor" in w for w in warnings)


def test_led_with_series_resistor_is_ok():
    # D1 anode -> LEDA net -> R1 -> VCC. The LED shares LEDA with a resistor.
    nodes = [
        _board(_rect_outline()),
        _net("VCC", 1),
        _net("GND", 2),
        _net("LEDA", 3),
        _component("D1", "LED", "LED_SMD:LED_0805_2012Metric", ["LEDA", "GND"]),
        _component("R1", "330R", "Resistor_SMD:R_0805_2012Metric", ["VCC", "LEDA"]),
    ]
    _errors, warnings = _errors_warnings(nodes)
    assert not any("current-limiting resistor" in w for w in warnings)


# --------------------------------------------------------------------------- #
# 2. decoupling capacitor per power net
# --------------------------------------------------------------------------- #
def test_power_net_without_decoupling_cap_warns():
    nodes = [
        _board(_rect_outline()),
        _net("VCC", 1),
        _net("GND", 2),
        _component("U1", "ATmega328P", "Package_QFP:TQFP-32_7x7mm_P0.8mm", ["VCC", "GND"]),
    ]
    _errors, warnings = _errors_warnings(nodes)
    assert any("Power net VCC has no decoupling capacitor" in w for w in warnings)


def test_power_net_with_decoupling_cap_is_ok():
    nodes = [
        _board(_rect_outline()),
        _net("VCC", 1),
        _net("GND", 2),
        _component("U1", "ATmega328P", "Package_QFP:TQFP-32_7x7mm_P0.8mm", ["VCC", "GND"]),
        _component("C1", "100nF", "Capacitor_SMD:C_0805_2012Metric", ["VCC", "GND"]),
    ]
    _errors, warnings = _errors_warnings(nodes)
    assert not any("decoupling capacitor" in w for w in warnings)


# --------------------------------------------------------------------------- #
# 3. capacitor voltage rating
# --------------------------------------------------------------------------- #
def test_underrated_cap_voltage_warns():
    nodes = [
        _board(_rect_outline()),
        _net("12V", 1),
        _net("GND", 2),
        _component("C1", "10uF 10V", "Capacitor_SMD:C_0805_2012Metric", ["12V", "GND"]),
    ]
    _errors, warnings = _errors_warnings(nodes)
    assert any("C1 voltage rating 10V may be insufficient for net 12V" in w for w in warnings)


def test_adequately_rated_cap_is_ok():
    # 25V >= 2 * 12V, so no warning.
    nodes = [
        _board(_rect_outline()),
        _net("12V", 1),
        _net("GND", 2),
        _component("C1", "10uF 25V", "Capacitor_SMD:C_0805_2012Metric", ["12V", "GND"]),
    ]
    _errors, warnings = _errors_warnings(nodes)
    assert not any("voltage rating" in w for w in warnings)


# --------------------------------------------------------------------------- #
# 4. undefined net references (error)
# --------------------------------------------------------------------------- #
def test_undefined_net_reference_is_error():
    nodes = [
        _board(_rect_outline()),
        _net("GND", 2),
        _component("U1", "ATmega328P", "Package_QFP:TQFP-32_7x7mm_P0.8mm", ["MISSING", "GND"]),
    ]
    errors, _warnings = _errors_warnings(nodes)
    assert any("Component U1 pad 1 references undefined net MISSING" in e for e in errors)


def test_all_nets_defined_has_no_error():
    nodes = [
        _board(_rect_outline()),
        _net("VCC", 1),
        _net("GND", 2),
        _component("U1", "ATmega328P", "Package_QFP:TQFP-32_7x7mm_P0.8mm", ["VCC", "GND"]),
    ]
    errors, _warnings = _errors_warnings(nodes)
    assert not any("undefined net" in e for e in errors)


# --------------------------------------------------------------------------- #
# 5. missing board outline
# --------------------------------------------------------------------------- #
def test_board_without_outline_warns():
    errors, warnings = _errors_warnings([_board([]), _net("GND", 1)])
    assert any("Board has no outline defined" in w for w in warnings)


def test_board_with_outline_is_ok():
    errors, warnings = _errors_warnings([_board(_rect_outline()), _net("GND", 1)])
    assert not any("no outline" in w for w in warnings)


# --------------------------------------------------------------------------- #
# wiring: validate_document surfaces hardware warnings and errors
# --------------------------------------------------------------------------- #
def test_validate_document_surfaces_hardware_warning():
    doc = {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "t", "generator": "test"},
        "nodes": [
            _board(_rect_outline()),
            _net("VCC", 1),
            _net("GND", 2),
            _component("U1", "ATmega328P", "Package_QFP:TQFP-32_7x7mm_P0.8mm", ["VCC", "GND"]),
        ],
    }
    result = tools.validate_document(document=doc)
    assert result["valid"] is True  # warnings do not fail validation
    assert any("decoupling capacitor" in w for w in result["warnings"])


def test_validate_document_fails_on_hardware_error():
    doc = {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "t", "generator": "test"},
        "nodes": [
            _board(_rect_outline()),
            _net("GND", 2),
            _component("U1", "ATmega328P", "Package_QFP:TQFP-32_7x7mm_P0.8mm", ["MISSING", "GND"]),
        ],
    }
    result = tools.validate_document(document=doc)
    assert result["valid"] is False
    assert "undefined net MISSING" in result["error"]
