"""A library of pre-built component definitions for the hardware domain.

Each entry pairs a real KiCad footprint with datasheet-accurate pad positions so
an agent can drop a known-good part into a document instead of inventing a
footprint and guessing pad coordinates. TQFP/QFP packages get their geometry from
``calculate_pad_positions`` (the same deterministic layout the calc tools expose);
everything else carries hand-specified positions taken from the part's datasheet.

A definition is footprint-level, not placement-level: it has ``value``,
``footprint``, ``description`` and ``pads`` (each ``{"number", "at"}``), but no
``reference``/``at``/``layer`` — those belong to the placed instance. To build a
hardware ``component`` node, merge a definition with a reference, a layer and a
board position.
"""

from __future__ import annotations

from typing import Any

from forgelab.calc import calculate_pad_positions


def _round(value: float) -> float:
    return round(value, 4)


def _inline(count: int, pitch: float, *, vertical: bool = False) -> list[dict[str, Any]]:
    """A single in-line row of ``count`` pads at ``pitch`` mm, centred on origin."""
    start = -(count - 1) * pitch / 2.0
    pads: list[dict[str, Any]] = []
    for i in range(count):
        coord = _round(start + i * pitch)
        at = [0.0, coord] if vertical else [coord, 0.0]
        pads.append({"number": str(i + 1), "at": at})
    return pads


def _two_pad(spacing: float) -> list[dict[str, Any]]:
    """Two pads on the X axis, ``spacing`` mm apart (SMD passives)."""
    half = spacing / 2.0
    return [
        {"number": "1", "at": [_round(-half), 0.0]},
        {"number": "2", "at": [_round(half), 0.0]},
    ]


def _dual_row(count: int, pitch: float, row_spacing: float) -> list[dict[str, Any]]:
    """A two-row package (pin 1 top-left, counter-clockwise) — SOIC/SOP/headers."""
    if count % 2:
        raise ValueError("a dual-row package needs an even pad count")
    per_side = count // 2
    x = row_spacing / 2.0
    top = (per_side - 1) * pitch / 2.0
    pads: list[dict[str, Any]] = []
    for i in range(per_side):  # left column, top to bottom
        pads.append({"number": str(i + 1), "at": [_round(-x), _round(top - i * pitch)]})
    for i in range(per_side):  # right column, bottom to top
        pads.append({"number": str(per_side + i + 1), "at": [_round(x), _round(-top + i * pitch)]})
    return pads


def _quad(count: int, pitch: float, span_to_side: float) -> list[dict[str, Any]]:
    """A leadless quad package (QFN/DFN): pins on four sides, pin 1 top-left CCW."""
    if count % 4:
        raise ValueError("a quad package needs a pad count divisible by 4")
    per_side = count // 4
    half = (per_side - 1) * pitch / 2.0
    pads: list[dict[str, Any]] = []
    number = 0

    def add(x: float, y: float) -> None:
        nonlocal number
        number += 1
        pads.append({"number": str(number), "at": [_round(x), _round(y)]})

    for i in range(per_side):  # left, top to bottom
        add(-span_to_side, half - i * pitch)
    for i in range(per_side):  # bottom, left to right
        add(-half + i * pitch, -span_to_side)
    for i in range(per_side):  # right, bottom to top
        add(span_to_side, -half + i * pitch)
    for i in range(per_side):  # top, right to left
        add(half - i * pitch, span_to_side)
    return pads


def _sot223() -> list[dict[str, Any]]:
    """SOT-223: three pins (2.3mm pitch) opposite a large tab (pin 4 = pin 2 net)."""
    return [
        {"number": "1", "at": [-2.3, -3.0]},
        {"number": "2", "at": [0.0, -3.0]},
        {"number": "3", "at": [2.3, -3.0]},
        {"number": "4", "at": [0.0, 3.0]},  # tab
    ]


def _sot23_3() -> list[dict[str, Any]]:
    """SOT-23-3: pins 1,2 on one side (0.95mm pitch), pin 3 opposite."""
    return [
        {"number": "1", "at": [-0.95, -1.1]},
        {"number": "2", "at": [0.95, -1.1]},
        {"number": "3", "at": [0.0, 1.1]},
    ]


def _to220_3() -> list[dict[str, Any]]:
    """TO-220-3 through-hole: three leads in a row at 2.54mm pitch."""
    return _inline(3, 2.54)


def _esp32_wroom() -> list[dict[str, Any]]:
    """ESP32-WROOM-32 castellated module: 18 pads per long edge at 1.27mm pitch."""
    per_side = 18
    pitch = 1.27
    x = 9.0  # half the 18mm module width
    top = (per_side - 1) * pitch / 2.0
    pads: list[dict[str, Any]] = []
    for i in range(per_side):  # left edge, top to bottom
        pads.append({"number": str(i + 1), "at": [_round(-x), _round(top - i * pitch)]})
    for i in range(per_side):  # right edge, bottom to top
        pads.append({"number": str(per_side + i + 1), "at": [_round(x), _round(-top + i * pitch)]})
    return pads


def _usb_b() -> list[dict[str, Any]]:
    """USB-B: 4 signal pins (VBUS, D-, D+, GND) plus two shield/mount pads."""
    return [
        {"number": "1", "at": [-1.25, -3.5]},  # VBUS
        {"number": "2", "at": [-3.75, -1.0]},  # D-
        {"number": "3", "at": [3.75, -1.0]},  # D+
        {"number": "4", "at": [1.25, -3.5]},  # GND
        {"number": "5", "at": [-5.65, 2.5]},  # shield
        {"number": "6", "at": [5.65, 2.5]},  # shield
    ]


def _usb_c_16p() -> list[dict[str, Any]]:
    """USB-C 16-pin receptacle: 12 signal pads (two rows, 0.5mm pitch) + 4 mounts."""
    pitch = 0.5
    signal = _dual_row(12, pitch, 2.4)
    mounts = [
        {"number": "13", "at": [-4.32, 1.8]},
        {"number": "14", "at": [4.32, 1.8]},
        {"number": "15", "at": [-4.32, -1.8]},
        {"number": "16", "at": [4.32, -1.8]},
    ]
    return signal + mounts


# Build the TQFP microcontroller pad lists from the deterministic calc layout, so
# the library and the calculate_pad_positions tool agree pad-for-pad.
def _tqfp(count: int, pitch: float) -> list[dict[str, Any]]:
    return [
        {"number": p["number"], "at": p["at"]} for p in calculate_pad_positions("QFP", pitch, count)
    ]


def _component(
    value: str, footprint: str, description: str, pads: list[dict[str, Any]]
) -> dict[str, Any]:
    return {"value": value, "footprint": footprint, "description": description, "pads": pads}


# --------------------------------------------------------------------------- #
# The library, grouped by category. Keys are the canonical component names.
# --------------------------------------------------------------------------- #
_LIBRARY: dict[str, dict[str, dict[str, Any]]] = {
    "Microcontrollers": {
        "ESP32-WROOM-32": _component(
            "ESP32-WROOM-32",
            "RF_Module:ESP32-WROOM-32",
            "Wi-Fi/BLE SoC module, castellated, 18 pads per long edge",
            _esp32_wroom(),
        ),
        "ATmega328P": _component(
            "ATmega328P",
            "Package_QFP:TQFP-32_7x7mm_P0.8mm",
            "8-bit AVR microcontroller, TQFP-32 (0.8mm pitch)",
            _tqfp(32, 0.8),
        ),
        "ATmega2560": _component(
            "ATmega2560",
            "Package_QFP:TQFP-100_14x14mm_P0.5mm",
            "8-bit AVR microcontroller, TQFP-100 (0.5mm pitch)",
            _tqfp(100, 0.5),
        ),
    },
    "Regulators": {
        "AMS1117-3.3": _component(
            "AMS1117-3.3",
            "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            "1A LDO regulator, fixed 3.3V output, SOT-223",
            _sot223(),
        ),
        "AMS1117-5.0": _component(
            "AMS1117-5.0",
            "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            "1A LDO regulator, fixed 5.0V output, SOT-223",
            _sot223(),
        ),
        "LM7805": _component(
            "LM7805",
            "Package_TO_SOT_THT:TO-220-3_Vertical",
            "1A linear regulator, fixed 5V output, TO-220-3",
            _to220_3(),
        ),
        "MCP1700-3302": _component(
            "MCP1700-3302",
            "Package_TO_SOT_SMD:SOT-23-3",
            "250mA LDO regulator, fixed 3.3V output, SOT-23-3",
            _sot23_3(),
        ),
    },
    "USB": {
        "CH340G": _component(
            "CH340G",
            "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
            "USB-to-serial UART bridge, SOP-16 (1.27mm pitch)",
            _dual_row(16, 1.27, 5.2),
        ),
        "CP2102": _component(
            "CP2102",
            "Package_DFN_QFN:QFN-28-1EP_5x5mm_P0.5mm",
            "USB-to-UART bridge, QFN-28 (0.5mm pitch)",
            _quad(28, 0.5, 2.5),
        ),
        "USB-B": _component(
            "USB-B",
            "Connector_USB:USB_B_OST_USB-B1HSB6",
            "USB Type-B through-hole receptacle",
            _usb_b(),
        ),
        "USB-C-16P": _component(
            "USB-C-16P",
            "Connector_USB:USB_C_Receptacle_GCT_USB4085",
            "USB Type-C 16-pin receptacle (power + USB 2.0)",
            _usb_c_16p(),
        ),
    },
    "Passives": {
        "R0402": _component(
            "10k",
            "Resistor_SMD:R_0402_1005Metric",
            "Chip resistor, 0402 (1005 metric)",
            _two_pad(0.95),
        ),
        "R0603": _component(
            "10k",
            "Resistor_SMD:R_0603_1608Metric",
            "Chip resistor, 0603 (1608 metric)",
            _two_pad(1.6),
        ),
        "R0805": _component(
            "10k",
            "Resistor_SMD:R_0805_2012Metric",
            "Chip resistor, 0805 (2012 metric)",
            _two_pad(2.0),
        ),
        "C0402": _component(
            "100nF",
            "Capacitor_SMD:C_0402_1005Metric",
            "Ceramic capacitor, 0402 (1005 metric)",
            _two_pad(0.95),
        ),
        "C0603": _component(
            "100nF",
            "Capacitor_SMD:C_0603_1608Metric",
            "Ceramic capacitor, 0603 (1608 metric)",
            _two_pad(1.6),
        ),
        "C0805": _component(
            "100nF",
            "Capacitor_SMD:C_0805_2012Metric",
            "Ceramic capacitor, 0805 (2012 metric)",
            _two_pad(2.0),
        ),
        "LED0805": _component(
            "LED", "LED_SMD:LED_0805_2012Metric", "LED, 0805 (2012 metric)", _two_pad(2.0)
        ),
    },
    "Sensors": {
        "DHT22": _component(
            "DHT22",
            "Sensor:Aosong_DHT22_AM2302_P2.54mm",
            "Temperature/humidity sensor, 4-pin SIP (VCC/DATA/NC/GND, 2.54mm pitch)",
            _inline(4, 2.54),
        ),
        "BME280": _component(
            "BME280",
            "Package_LGA:Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering",
            "Environmental sensor (pressure/temp/humidity), LGA-8 2.5x2.5mm",
            _dual_row(8, 0.65, 2.4),
        ),
        "SCD40": _component(
            "SCD40",
            "Package_DFN_QFN:Sensirion_DFN-10_2.0x2.5mm_P0.5mm",
            "CO2/temperature/humidity sensor, DFN-10 2.0x2.5mm",
            _dual_row(10, 0.5, 1.6),
        ),
    },
    "Connectors": {
        **{
            f"PinHeader-1x{n}": _component(
                f"Conn_01x{n:02d}",
                f"Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical",
                f"2.54mm pin header, 1x{n}",
                _inline(n, 2.54, vertical=True),
            )
            for n in range(2, 11)
        },
        "PinHeader-2x3-ICSP": _component(
            "ICSP",
            "Connector_PinHeader_2.54mm:PinHeader_2x03_P2.54mm_Vertical",
            "2.54mm 2x3 ICSP/ISP programming header",
            _dual_row(6, 2.54, 2.54),
        ),
        "JST-PH-2": _component(
            "Battery",
            "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
            "JST-PH 2-pin battery connector (2.0mm pitch)",
            _inline(2, 2.0),
        ),
    },
}

# Flat name -> definition index, plus name -> category, for O(1) lookup.
_BY_NAME: dict[str, dict[str, Any]] = {}
_CATEGORY_OF: dict[str, str] = {}
for _category, _members in _LIBRARY.items():
    for _name, _definition in _members.items():
        _BY_NAME[_name] = _definition
        _CATEGORY_OF[_name] = _category


def list_components() -> dict[str, list[str]]:
    """Return every component name grouped by category."""
    return {category: list(members) for category, members in _LIBRARY.items()}


def get_component(name: str) -> dict[str, Any]:
    """Return a copy of a component's full definition (case-insensitive name).

    The result carries ``name``, ``category``, ``value``, ``footprint``,
    ``description`` and ``pads`` (each ``{"number", "at"}``) — ready to merge with
    a reference, layer and board position into a hardware ``component`` node.

    Raises ``KeyError`` if the name is unknown.
    """
    definition = _BY_NAME.get(name)
    if definition is None:
        # Fall back to a case-insensitive match before giving up.
        lowered = name.lower()
        for known, known_def in _BY_NAME.items():
            if known.lower() == lowered:
                definition = known_def
                name = known
                break
    if definition is None:
        raise KeyError(name)
    return {
        "name": name,
        "category": _CATEGORY_OF[name],
        "value": definition["value"],
        "footprint": definition["footprint"],
        "description": definition["description"],
        "pads": [dict(pad) for pad in definition["pads"]],
    }
