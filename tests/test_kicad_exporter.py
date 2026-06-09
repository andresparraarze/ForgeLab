from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.formats import parse
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    Component,
    DesignRules,
    DocumentMeta,
    Domain,
    ForgeDocument,
    Net,
    Node,
    Pad,
)
from forgelab.spec.version import SPEC_VERSION


def _doc():
    board = BoardConstraints(
        kicad_version="20221018",
        generator="forgelab",
        layers=[],
        outline=[],
        design_rules=DesignRules(clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4),
    )
    nets = [Net(code=0, name=""), Net(code=1, name="GND"), Net(code=2, name="LED_A")]
    comp = Component(
        reference="R1",
        value="330R",
        footprint="Resistor_SMD:R_0603_1608Metric",
        layer="F.Cu",
        at=[100.0, 50.0, 0.0],
        pads=[Pad(number="1", net="LED_A"), Pad(number="2", net="GND")],
        uuid="abc",
    )
    nodes = [Node(id=NODE_BOARD, type=NODE_BOARD, props=board.model_dump())]
    nodes += [Node(id=f"net:{n.code}", type=NODE_NET, props=n.model_dump()) for n in nets]
    nodes.append(Node(id="R1", type=NODE_COMPONENT, props=comp.model_dump()))
    return ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.HARDWARE,
        meta=DocumentMeta(name="t", generator="test"),
        nodes=nodes,
    )


def test_export_produces_valid_kicad_root():
    out = KiCadExporter().from_ir(_doc())
    tree = parse(out.decode("utf-8"))
    assert tree[0] == "kicad_pcb"


def test_export_contains_nets_and_footprint():
    out = KiCadExporter().from_ir(_doc()).decode("utf-8")
    assert '(net 1 "GND")' in out
    assert "Resistor_SMD:R_0603_1608Metric" in out
    assert '(property "Reference" "R1")' in out


def test_export_resolves_pad_net_codes():
    tree = parse(KiCadExporter().from_ir(_doc()).decode("utf-8"))
    footprints = [c for c in tree if isinstance(c, list) and c and c[0] == "footprint"]
    pads = [c for c in footprints[0] if isinstance(c, list) and c and c[0] == "pad"]
    pad_nets = {}
    for pad in pads:
        net = next(c for c in pad if isinstance(c, list) and c[0] == "net")
        pad_nets[pad[1]] = (net[1], net[2])
    assert pad_nets["1"] == (2, "LED_A")
    assert pad_nets["2"] == (1, "GND")
