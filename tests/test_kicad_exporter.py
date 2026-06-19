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


def _export_with_version(kicad_version: str) -> str:
    doc = _doc()
    board_node = next(n for n in doc.nodes if n.type == NODE_BOARD)
    board = BoardConstraints.model_validate(board_node.props)
    board.kicad_version = kicad_version
    board_node.props = board.model_dump()
    return KiCadExporter().from_ir(doc).decode("utf-8")


def test_semver_version_is_written_as_unquoted_integer():
    # Live KiCad bug: (version "7.0") is rejected; the format version is a bare
    # integer date stamp. "7.0" must map to its date-format version, unquoted.
    out = _export_with_version("7.0")
    assert "(version 20221018)" in out
    assert '(version "7.0")' not in out


def test_integer_version_string_stays_unquoted():
    out = _export_with_version("20240108")
    assert "(version 20240108)" in out
    assert '(version "20240108)' not in out


def test_unrecognized_version_falls_back_to_canonical():
    out = _export_with_version("nonsense")
    assert "(version 20221018)" in out
    assert "nonsense" not in out


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


def _tree():
    from forgelab.formats import parse

    return parse(KiCadExporter().from_ir(_doc()).decode())


def _blocks(tree, tag):
    return [e for e in tree if isinstance(e, list) and e and str(e[0]) == tag]


def test_design_rules_live_in_net_class_not_setup():
    # KiCad 9 rejects rule keys inside (setup ...); they belong in net classes.
    tree = _tree()
    setup = _blocks(tree, "setup")[0]
    setup_keys = {str(e[0]) for e in setup if isinstance(e, list) and e}
    assert not {"clearance", "trace_width", "via_diameter", "via_dia", "via_drill"} & setup_keys
    (net_class,) = _blocks(tree, "net_class")
    assert str(net_class[1]) == "Default"
    nc_keys = {str(e[0]): e[1] for e in net_class if isinstance(e, list) and e}
    assert nc_keys["clearance"] == 0.2
    assert nc_keys["trace_width"] == 0.25
    assert nc_keys["via_dia"] == 0.8
    assert nc_keys["via_drill"] == 0.4
    added = [e[1] for e in net_class if isinstance(e, list) and str(e[0]) == "add_net"]
    assert set(added) == {"GND", "LED_A"}


def _pad_at(pad):
    sub = {str(e[0]): e for e in pad if isinstance(e, list) and e}
    return tuple(sub["at"][1:3])


def _multi_pad_doc(n_pads: int, with_positions: bool = False):
    pads = []
    for i in range(n_pads):
        kwargs = {"number": str(i + 1), "net": ""}
        if with_positions:
            kwargs["at"] = [float(i), float(i * 2)]
        pads.append(Pad(**kwargs))
    comp = Component(
        reference="U1",
        value="HTSSOP",
        footprint="Package_SO:HTSSOP-28",
        layer="F.Cu",
        at=[100.0, 50.0, 0.0],
        pads=pads,
    )
    board = BoardConstraints(
        kicad_version="20221018",
        generator="forgelab",
        layers=[],
        outline=[],
        design_rules=DesignRules(clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4),
    )
    nodes = [
        Node(id=NODE_BOARD, type=NODE_BOARD, props=board.model_dump()),
        Node(id="net:0", type=NODE_NET, props=Net(code=0, name="").model_dump()),
        Node(id="U1", type=NODE_COMPONENT, props=comp.model_dump()),
    ]
    return ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.HARDWARE,
        meta=DocumentMeta(name="t", generator="test"),
        nodes=nodes,
    )


def test_pads_have_at_and_size():
    tree = _tree()
    footprints = _blocks(tree, "footprint")
    pads = [e for fp in footprints for e in fp if isinstance(e, list) and str(e[0]) == "pad"]
    assert pads
    for pad in pads:
        sub = {str(e[0]): e for e in pad if isinstance(e, list) and e}
        assert len(sub["at"]) >= 3  # (at x y)
        assert sub["size"][1:3] == [1.6, 1.6]


def test_unpositioned_pads_do_not_stack_at_origin():
    # The core bug: every pad got (at 0 0) and collapsed onto the footprint
    # origin. Un-positioned pads must now be spread to distinct positions.
    tree = parse(KiCadExporter().from_ir(_multi_pad_doc(8)).decode())
    (fp,) = _blocks(tree, "footprint")
    pads = [e for e in fp if isinstance(e, list) and str(e[0]) == "pad"]
    assert len(pads) == 8
    positions = [_pad_at(p) for p in pads]
    assert len(set(positions)) == len(positions), positions


def test_pad_at_offset_is_emitted_when_provided():
    # Agent-supplied pad offsets are honored verbatim, not overwritten.
    tree = parse(KiCadExporter().from_ir(_multi_pad_doc(4, with_positions=True)).decode())
    (fp,) = _blocks(tree, "footprint")
    pads = [e for e in fp if isinstance(e, list) and str(e[0]) == "pad"]
    positions = [_pad_at(p) for p in pads]
    assert positions == [(0, 0), (1, 2), (2, 4), (3, 6)]


def test_outline_uses_stroke_syntax():
    from forgelab.formats import parse
    from forgelab.spec import OutlineSegment

    doc = _doc()
    board_node = next(n for n in doc.nodes if n.type == "board")
    board = BoardConstraints.model_validate(board_node.props)
    board.outline = [OutlineSegment(start=[0, 0], end=[10, 0])]
    board_node.props = board.model_dump()
    tree = parse(KiCadExporter().from_ir(doc).decode())
    lines = _blocks(tree, "gr_line")
    assert lines
    for line in lines:
        sub = {str(e[0]): e for e in line if isinstance(e, list) and e}
        assert "width" not in sub, "pre-KiCad-6 bare (width ...) is rejected by KiCad 9"
        stroke = {str(e[0]): e for e in sub["stroke"] if isinstance(e, list)}
        assert stroke["width"][1] == 0.1
        assert str(stroke["type"][1]) == "solid"
