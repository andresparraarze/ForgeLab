from pathlib import Path

import pytest

from forgelab.formats import parse
from forgelab.importers.hardware.kicad import KiCadImporter, KiCadParseError
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    Component,
    Net,
)

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "hardware" / "blinky.kicad_pcb"


def test_fixture_parses_as_kicad_pcb():
    tree = parse(FIXTURE.read_text())
    assert tree[0] == "kicad_pcb"


def _import():
    return KiCadImporter().to_ir(FIXTURE.read_bytes())


def test_import_has_board_nets_components():
    doc = _import()
    boards = [n for n in doc.nodes if n.type == NODE_BOARD]
    nets = [n for n in doc.nodes if n.type == NODE_NET]
    comps = [n for n in doc.nodes if n.type == NODE_COMPONENT]
    assert len(boards) == 1
    assert len(nets) == 4  # "", GND, +3V3, LED_A
    assert len(comps) == 2


def test_import_components_have_expected_data():
    doc = _import()
    comps = {n.id: Component.model_validate(n.props) for n in doc.nodes if n.type == NODE_COMPONENT}
    r1 = comps["R1"]
    assert r1.value == "330R"
    assert r1.footprint == "Resistor_SMD:R_0603_1608Metric"
    assert r1.at == [100.0, 50.0, 0.0]
    assert {p.number: p.net for p in r1.pads} == {"1": "+3V3", "2": "LED_A"}
    d1 = comps["D1"]
    assert d1.value == "RED"
    assert {p.number: p.net for p in d1.pads} == {"1": "LED_A", "2": "GND"}


def test_import_board_constraints():
    doc = _import()
    board = next(n for n in doc.nodes if n.type == NODE_BOARD)
    bc = BoardConstraints.model_validate(board.props)
    assert bc.kicad_version == "20240108"
    assert bc.design_rules.clearance == 0.2
    assert bc.design_rules.track_width == 0.25
    assert len(bc.outline) == 4  # rectangle
    assert len(bc.layers) == 3


def test_import_nets_sorted_by_code():
    doc = _import()
    nets = [Net.model_validate(n.props) for n in doc.nodes if n.type == NODE_NET]
    assert [n.code for n in nets] == [0, 1, 2, 3]


def test_import_garbage_raises_parse_error():
    with pytest.raises(KiCadParseError):
        KiCadImporter().to_ir(b"not a kicad file")
    with pytest.raises(KiCadParseError):
        KiCadImporter().to_ir(b"(other_root (version 1))")
