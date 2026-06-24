import pytest
from pydantic import ValidationError

from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    BoardLayer,
    Component,
    DesignRules,
    Net,
    OutlineSegment,
    Pad,
)


def test_node_type_constants():
    assert NODE_COMPONENT == "component"
    assert NODE_NET == "net"
    assert NODE_BOARD == "board"


def test_component_roundtrips_through_dict():
    comp = Component(
        reference="R1",
        value="330R",
        footprint="Resistor_SMD:R_0603_1608Metric",
        layer="F.Cu",
        at=[100.0, 50.0, 0.0],
        pads=[Pad(number="1", net="LED_A"), Pad(number="2", net="GND")],
        uuid="abc",
    )
    restored = Component.model_validate(comp.model_dump())
    assert restored == comp
    assert restored.pads[0].net == "LED_A"


def test_component_at_xy_is_normalized_to_zero_rotation():
    # [x, y] is shorthand for [x, y, 0] (an implicit zero rotation).
    comp = Component(reference="R1", value="330R", footprint="x", layer="F.Cu", at=[1.0, 2.0])
    assert comp.at == [1.0, 2.0, 0.0]


def test_component_at_rejects_wrong_length():
    with pytest.raises(ValidationError):
        Component(
            reference="R1",
            value="330R",
            footprint="x",
            layer="F.Cu",
            at=[1.0, 2.0, 3.0, 4.0],
        )


def test_net_and_board_validate():
    net = Net(code=1, name="GND")
    assert net.code == 1
    board = BoardConstraints(
        kicad_version="20221018",
        generator="pcbnew",
        layers=[BoardLayer(ordinal=0, canonical_name="F.Cu", layer_type="signal")],
        outline=[OutlineSegment(start=[0.0, 0.0], end=[10.0, 0.0])],
        design_rules=DesignRules(clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4),
    )
    assert board.layers[0].canonical_name == "F.Cu"
    assert board.design_rules.clearance == 0.2
