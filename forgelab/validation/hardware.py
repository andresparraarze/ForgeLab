"""Engineering rule checks for hardware-domain documents.

These run after structural (Pydantic) validation as a pre-flight before KiCad:
they catch electrical design mistakes — an LED with no series resistor, a power
net with no decoupling cap, an under-rated capacitor, an undefined net reference,
a board with no outline — that a netlist-level structural check cannot see. Like
the mechanical checks, they return human-readable ``errors`` (fatal — the
document should not be considered valid) and ``warnings`` (non-fatal — surfaced
to the agent but not blocking).

Pure standard library. Node payloads are read as plain dicts (``Node.props``).
"""

from __future__ import annotations

import re
from typing import Any

from forgelab.layout import component_bbox
from forgelab.spec import Domain, ForgeDocument, Node
from forgelab.spec.hardware import NODE_BOARD, NODE_COMPONENT, NODE_NET

# Power nets we expect to be decoupled and to use as a hint for the LED check.
_POWER_NET_NAMES = {"VCC", "VDD", "3V3", "5V", "VBUS"}
# Ground-net names: a resistor sharing only ground with an LED is not a series
# current-limiting resistor, so ground nets are excluded from that check.
_GROUND_NET_NAMES = {"GND", "GROUND", "VSS", "AGND", "DGND"}

# A voltage token like "25V" inside a value, but not the "3V3" net-style form
# (the V must not be followed by a digit).
_VOLTAGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*V(?![0-9])", re.IGNORECASE)


def _norm_net(name: str) -> str:
    return name.upper().lstrip("+").replace("3.3V", "3V3").replace("5.0V", "5V")


def _is_power_net(name: str) -> bool:
    return _norm_net(name) in _POWER_NET_NAMES


def _is_ground_net(name: str) -> bool:
    norm = _norm_net(name)
    return norm in _GROUND_NET_NAMES or norm.startswith("GND")


def _net_voltage(name: str) -> float | None:
    """Infer a net's nominal supply voltage from its name, or None if unknown."""
    norm = _norm_net(name)
    m = re.fullmatch(r"(\d+)V(\d+)", norm)  # 3V3 -> 3.3
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)V", norm)  # 5V, 12V
    if m:
        return float(m.group(1))
    if norm == "VBUS":
        return 5.0
    return None  # VCC / VDD / signal nets carry no inferable voltage


def _value(comp: Node) -> str:
    return str(comp.props.get("value", ""))


def _reference(comp: Node) -> str:
    return str(comp.props.get("reference", "") or comp.id)


def _footprint(comp: Node) -> str:
    return str(comp.props.get("footprint", ""))


def _is_led(comp: Node) -> bool:
    return "LED" in _value(comp).upper()


def _is_resistor(comp: Node) -> bool:
    return "resistor" in _footprint(comp).lower() or bool(re.match(r"^[Rr]\d", _reference(comp)))


def _is_capacitor(comp: Node) -> bool:
    return "capacitor" in _footprint(comp).lower() or bool(re.match(r"^[Cc]\d", _reference(comp)))


def _is_decoupling_cap(comp: Node) -> bool:
    value = _value(comp).lower()
    return "nf" in value or "100n" in value or "10n" in value


def _voltage_rating(value: str) -> float | None:
    m = _VOLTAGE_RE.search(value)
    return float(m.group(1)) if m else None


def _pads(comp: Node) -> list[dict[str, Any]]:
    return [p for p in (comp.props.get("pads") or []) if isinstance(p, dict)]


def check_hardware(document: ForgeDocument) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a hardware document.

    For non-hardware documents the checks do not apply and two empty lists are
    returned, so callers can run this unconditionally.
    """
    if document.domain != Domain.HARDWARE:
        return [], []

    nodes = list(document.walk())
    errors: list[str] = []
    warnings: list[str] = []

    components = [n for n in nodes if n.type == NODE_COMPONENT]
    net_nodes = [n for n in nodes if n.type == NODE_NET]
    board_nodes = [n for n in nodes if n.type == NODE_BOARD]

    defined_nets = {str(n.props.get("name", "")) for n in net_nodes}
    defined_nets.discard("")

    # net name -> components with a pad on it.
    net_to_comps: dict[str, list[Node]] = {}
    for comp in components:
        for pad in _pads(comp):
            net = str(pad.get("net", ""))
            if net:
                net_to_comps.setdefault(net, []).append(comp)

    def net_has_resistor(net: str) -> bool:
        return any(_is_resistor(c) for c in net_to_comps.get(net, []))

    # 1. LED without a current-limiting resistor (warning). An LED is fine if it
    #    shares a non-ground net with a resistor (the series resistor's net).
    for comp in components:
        if not _is_led(comp):
            continue
        led_nets = [str(p.get("net", "")) for p in _pads(comp) if p.get("net")]
        signal_nets = [n for n in led_nets if not _is_ground_net(n)]
        if any(net_has_resistor(n) for n in signal_nets):
            continue
        report_net = next((n for n in led_nets if _is_power_net(n)), None)
        if report_net is None:
            report_net = signal_nets[0] if signal_nets else (led_nets[0] if led_nets else None)
        if report_net is not None:
            warnings.append(
                f"LED {_reference(comp)} on net {report_net} has no current-limiting "
                f"resistor — add a series resistor to prevent damage"
            )

    # 2. Decoupling capacitor per power net (warning).
    decoupling_nets: set[str] = set()
    for comp in components:
        if _is_decoupling_cap(comp):
            decoupling_nets.update(str(p.get("net", "")) for p in _pads(comp) if p.get("net"))
    power_nets_present = sorted({n for n in (defined_nets | set(net_to_comps)) if _is_power_net(n)})
    for net in power_nets_present:
        if net not in decoupling_nets:
            warnings.append(
                f"Power net {net} has no decoupling capacitor — add a 100nF cap "
                f"close to each IC power pin"
            )

    # 3. Capacitor voltage rating vs inferred supply (warning): at least 2x.
    for comp in components:
        if not _is_capacitor(comp):
            continue
        rating = _voltage_rating(_value(comp))
        if rating is None:
            continue
        for pad in _pads(comp):
            net = str(pad.get("net", ""))
            supply = _net_voltage(net) if net else None
            if supply is not None and rating < 2 * supply:
                warnings.append(
                    f"{_reference(comp)} voltage rating {rating:g}V may be insufficient "
                    f"for net {net} — use a cap rated at least 2x the supply voltage"
                )
                break  # one warning per capacitor

    # 4. Undefined net references (error).
    for comp in components:
        ref = _reference(comp)
        for pad in _pads(comp):
            net = str(pad.get("net", ""))
            if net and net not in defined_nets:
                num = pad.get("number", "?")
                errors.append(f"Component {ref} pad {num} references undefined net {net}")

    # 5. Missing board outline (warning).
    for board in board_nodes:
        if not (board.props.get("outline") or []):
            warnings.append(
                "Board has no outline defined — add Edge.Cuts segments to define the board shape"
            )

    # 6. Component outside the board outline (error): the board literally will
    #    not fabricate correctly. Footprints are sized from positioned pads via
    #    the same bbox the auto-placer uses (without its keepout margin, which
    #    is a packing preference, not a physical bound); components with no
    #    positioned pads have nothing to bound and are skipped, as is the whole
    #    check when there is no outline (check 5 already warns about that).
    bounds = _outline_bbox(board_nodes)
    if bounds is not None:
        min_x, min_y, max_x, max_y = bounds
        outline_w, outline_h = max_x - min_x, max_y - min_y
        eps = 1e-6
        for comp in components:
            if not any(isinstance(p.get("at"), list) and len(p["at"]) == 2 for p in _pads(comp)):
                continue
            at = comp.props.get("at") or [0.0, 0.0]
            x, y = float(at[0]), float(at[1])
            x0, y0, x1, y1 = component_bbox(comp.props, keepout=0.0)
            if (
                x + x0 < min_x - eps
                or y + y0 < min_y - eps
                or x + x1 > max_x + eps
                or y + y1 > max_y + eps
            ):
                errors.append(
                    f"Component {_reference(comp)} extends outside the board outline — "
                    f"at ({x:g}, {y:g}) with footprint {x1 - x0:g}x{y1 - y0:g}mm exceeds "
                    f"board bounds ({outline_w:g}x{outline_h:g}mm). "
                    f"Run auto_place to fix automatically."
                )

    return errors, warnings


def _outline_bbox(board_nodes: list[Node]) -> tuple[float, float, float, float] | None:
    """(min_x, min_y, max_x, max_y) over the first board's outline segments."""
    for board in board_nodes:
        xs: list[float] = []
        ys: list[float] = []
        for seg in board.props.get("outline") or []:
            if not isinstance(seg, dict):
                continue
            for key in ("start", "end"):
                point = seg.get(key)
                if isinstance(point, list) and len(point) == 2:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
        if xs:
            return (min(xs), min(ys), max(xs), max(ys))
    return None
