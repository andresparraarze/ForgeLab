"""Electrical rule checking: is the board wired the way the netlist says?

Every other hardware check measures geometry — how far apart the copper is,
whether pads overlap, whether a part fits. None of them asked whether the copper
actually connects what the netlist claims, so a board with a third of its nets
unrouted reported `passed: True`. `tests/test_layout_routing.py` asserted that as
correct behaviour.
"""

import json
import subprocess
from pathlib import Path

from external_tools import requires_kicad_cli

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.layout.routing import route_document
from forgelab.spec import SPEC_VERSION, ForgeDocument
from forgelab.validation import check_connectivity, check_electrical, check_fab_rules

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "hardware"


def _doc(nodes: list[dict]) -> ForgeDocument:
    board = {
        "id": "board",
        "type": "board",
        "props": {
            "kicad_version": "20240108",
            "generator": "test",
            "layers": [
                {"ordinal": 0, "canonical_name": "F.Cu", "layer_type": "signal"},
                {"ordinal": 31, "canonical_name": "B.Cu", "layer_type": "signal"},
                {"ordinal": 44, "canonical_name": "Edge.Cuts", "layer_type": "user"},
            ],
            "outline": [
                {"start": [0, 0], "end": [30, 0]},
                {"start": [30, 0], "end": [30, 20]},
                {"start": [30, 20], "end": [0, 20]},
                {"start": [0, 20], "end": [0, 0]},
            ],
            "design_rules": {
                "clearance": 0.2,
                "track_width": 0.25,
                "via_diameter": 0.8,
                "via_drill": 0.4,
            },
        },
    }
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "erc", "generator": "test"},
            "nodes": [board, *nodes],
        }
    )


def _part(ref: str, x: float, y: float, nets: tuple[str, str], layer: str = "F.Cu") -> dict:
    return {
        "id": ref,
        "type": "component",
        "props": {
            "reference": ref,
            "value": "X",
            "footprint": "NotAReal:Part",
            "layer": layer,
            "at": [x, y, 0],
            "pads": [
                {"number": "1", "net": nets[0], "at": [-1.0, 0], "size": [1.0, 1.0]},
                {"number": "2", "net": nets[1], "at": [1.0, 0], "size": [1.0, 1.0]},
            ],
        },
    }


def _net(code: int, name: str) -> dict:
    return {"id": f"net:{code}", "type": "net", "props": {"code": code, "name": name}}


def _track(net: str, start: list, end: list, layer: str = "F.Cu") -> dict:
    return {
        "id": f"t_{net}_{start[0]}",
        "type": "track",
        "props": {"net": net, "layer": layer, "start": start, "end": end, "width": 0.25},
    }


# ------------------------------------------------------------- connectivity


def test_an_unrouted_net_is_reported():
    doc = _doc([_net(1, "SIG"), _part("R1", 5, 10, ("SIG", "")), _part("R2", 20, 10, ("SIG", ""))])
    (message,) = check_connectivity(doc)
    assert "SIG" in message and "2 unconnected groups" in message


def test_a_routed_net_is_not_reported():
    doc = _doc(
        [
            _net(1, "SIG"),
            _part("R1", 5, 10, ("SIG", "")),
            _part("R2", 20, 10, ("SIG", "")),
            _track("SIG", [4.0, 10.0], [19.0, 10.0]),
        ]
    )
    assert check_connectivity(doc) == []


def test_a_track_on_another_layer_does_not_connect():
    """Copper only joins what it shares a layer with."""
    doc = _doc(
        [
            _net(1, "SIG"),
            _part("R1", 5, 10, ("SIG", "")),
            _part("R2", 20, 10, ("SIG", "")),
            _track("SIG", [4.0, 10.0], [19.0, 10.0], layer="B.Cu"),
        ]
    )
    assert check_connectivity(doc) != []


def test_a_via_bridges_the_layers():
    """R2 is on the back, so the connection has to change layer to reach it."""
    doc = _doc(
        [
            _net(1, "SIG"),
            _part("R1", 5, 10, ("SIG", "")),
            _part("R2", 20, 10, ("SIG", ""), layer="B.Cu"),
            _track("SIG", [4.0, 10.0], [12.0, 10.0]),
            _track("SIG", [12.0, 10.0], [19.0, 10.0], layer="B.Cu"),
            {
                "id": "v1",
                "type": "via",
                "props": {"at": [12.0, 10.0], "net": "SIG", "size": 0.8, "drill": 0.4},
            },
        ]
    )
    assert check_connectivity(doc) == []


def test_a_single_pad_net_is_not_called_unrouted():
    """Nothing to connect it to; that is a modelling warning, not a routing one."""
    doc = _doc([_net(1, "SIG"), _part("R1", 5, 10, ("SIG", ""))])
    assert check_connectivity(doc) == []
    _errors, warnings = check_electrical(doc)
    assert any("only one pad" in w for w in warnings)


# ------------------------------------------------------------- netlist rules


def test_duplicate_reference_designators_are_an_error():
    doc = _doc([_net(1, "A"), _part("R1", 5, 5, ("A", "")), _part("R1", 15, 5, ("A", ""))])
    errors, _ = check_electrical(doc)
    assert any("R1" in e and "2 components" in e for e in errors)


def test_duplicate_net_codes_are_an_error():
    """The exporter writes the code, so two nets sharing one silently merge."""
    doc = _doc([_net(1, "A"), _net(1, "B")])
    errors, _ = check_electrical(doc)
    assert any("Net code 1" in e for e in errors)


def test_an_undeclared_layer_is_an_error():
    doc = _doc([_net(1, "A"), _part("R1", 5, 5, ("A", ""), layer="In1.Cu")])
    errors, _ = check_electrical(doc)
    assert any("In1.Cu" in e and "does not declare" in e for e in errors)


def test_a_net_with_no_pads_is_a_warning():
    _errors, warnings = check_electrical(_doc([_net(1, "ORPHAN")]))
    assert any("ORPHAN" in w and "no pads" in w for w in warnings)


# ------------------------------------------------- how it reaches the caller


def test_connectivity_is_advisory_during_authoring():
    """An unrouted board is a normal step, not an invalid document.

    validate_document runs throughout authoring; failing it between
    generate_document and route_board would break the ordinary workflow.
    """
    doc = _doc([_net(1, "SIG"), _part("R1", 5, 10, ("SIG", "")), _part("R2", 20, 10, ("SIG", ""))])
    errors, warnings = check_electrical(doc)
    assert errors == []
    assert any("not fully routed" in w for w in warnings)


def test_the_fab_check_still_passes_geometry_but_names_the_missing_net():
    from forgelab.validation import check_gerber_completeness

    doc = _doc([_net(1, "SIG"), _part("R1", 5, 10, ("SIG", "")), _part("R2", 20, 10, ("SIG", ""))])
    assert check_fab_rules(doc)["passed"] is True  # geometry is fine
    result = check_gerber_completeness(doc)
    assert any("SIG" in w and "not fully routed" in w for w in result["warnings"])


# ------------------------------------------------------- against KiCad itself


@requires_kicad_cli
def test_connectivity_agrees_with_kicad_and_raises_no_false_alarms(tmp_path):
    """The model is checked against the tool it is standing in for.

    On the routed Arduino Uno, KiCad names the nets it cannot see a connection
    for; every net ForgeLab reports must be one of them. The converse does not
    hold and is documented: a poured net's fill is KiCad's to compute, so
    ForgeLab can miss one. What it must never do is invent one.
    """
    data = json.loads((_EXAMPLES / "arduino_uno.forge.json").read_text())
    doc = ForgeDocument.model_validate(data)
    routed = route_document(doc)
    nodes = [n for n in data["nodes"] if n.get("type") not in ("track", "via", "zone")]
    for kind in ("tracks", "vias", "zones"):
        nodes.extend(
            {"id": f"{kind}_{i}", "type": kind[:-1], "props": props}
            for i, props in enumerate(routed[kind])
        )
    data["nodes"] = nodes
    doc = ForgeDocument.model_validate(data)

    board = tmp_path / "erc.kicad_pcb"
    board.write_bytes(KiCadExporter().from_ir(doc))
    report = tmp_path / "drc.json"
    subprocess.run(
        ["kicad-cli", "pcb", "drc", "--severity-all", "--refill-zones",
         "--format", "json", "-o", str(report), str(board)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert report.exists()

    kicad_nets = set()
    for violation in json.loads(report.read_text()).get("unconnected_items", []):
        for item in violation.get("items", []):
            text = item.get("description", "")
            if "[" in text:
                kicad_nets.add(text.split("[")[1].split("]")[0])

    mine = {m.split()[1] for m in check_connectivity(doc)}
    assert mine <= kicad_nets, f"reported nets KiCad considers connected: {mine - kicad_nets}"
    assert mine, "the routed Uno does leave nets unconnected; reporting none would be a miss"
