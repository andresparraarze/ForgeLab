import pytest
from pydantic import ValidationError

from forgelab.spec import (
    DEFAULT_ZONE_MIN_THICKNESS,
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    NODE_ZONE,
    BoardConstraints,
    BoardLayer,
    Component,
    DesignRules,
    Net,
    OutlineSegment,
    Pad,
    Zone,
)


def test_node_type_constants():
    assert NODE_COMPONENT == "component"
    assert NODE_NET == "net"
    assert NODE_BOARD == "board"
    assert NODE_ZONE == "zone"


def test_zone_roundtrips_and_defaults():
    zone = Zone(net="GND", layer="B.Cu", polygon=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
    # clearance defaults to None (inherit design_rules.clearance at export time).
    assert zone.clearance is None
    assert zone.min_thickness == DEFAULT_ZONE_MIN_THICKNESS
    assert Zone.model_validate(zone.model_dump()) == zone


def test_zone_rejects_fewer_than_three_points():
    with pytest.raises(ValidationError):
        Zone(net="GND", polygon=[[0.0, 0.0], [10.0, 0.0]])


def test_zone_rejects_non_xy_points():
    with pytest.raises(ValidationError):
        Zone(net="GND", polygon=[[0.0, 0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])


def test_zone_rejects_self_intersecting_polygon():
    # A bow-tie: edges (p0->p1) and (p2->p3) cross.
    with pytest.raises(ValidationError):
        Zone(net="GND", polygon=[[0.0, 0.0], [10.0, 10.0], [10.0, 0.0], [0.0, 10.0]])


def test_zone_accepts_a_simple_concave_polygon():
    # An L-shape is simple (non-self-intersecting) even though it is concave.
    zone = Zone(
        net="GND",
        polygon=[[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]],
    )
    assert len(zone.polygon) == 6


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
