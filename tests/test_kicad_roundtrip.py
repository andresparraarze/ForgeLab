from pathlib import Path

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.formats import parse
from forgelab.importers.hardware.kicad import KiCadImporter
from forgelab.spec import NODE_COMPONENT, NODE_NET, Component

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "hardware" / "blinky.kicad_pcb"


def test_semantic_roundtrip_is_stable():
    imp = KiCadImporter()
    exp = KiCadExporter()
    doc1 = imp.to_ir(FIXTURE.read_bytes())
    text = exp.from_ir(doc1)
    doc2 = imp.to_ir(text)
    assert doc1 == doc2


def test_roundtrip_preserves_counts_and_connectivity():
    imp = KiCadImporter()
    exp = KiCadExporter()
    doc1 = imp.to_ir(FIXTURE.read_bytes())
    doc2 = imp.to_ir(exp.from_ir(doc1))

    def comps(doc):
        return {
            n.id: Component.model_validate(n.props) for n in doc.nodes if n.type == NODE_COMPONENT
        }

    def net_names(doc):
        return sorted(n.props["name"] for n in doc.nodes if n.type == NODE_NET)

    c1, c2 = comps(doc1), comps(doc2)
    assert c1.keys() == c2.keys()
    for ref in c1:
        assert {p.number: p.net for p in c1[ref].pads} == {p.number: p.net for p in c2[ref].pads}
    assert net_names(doc1) == net_names(doc2)


def test_exported_file_is_valid_sexpr():
    doc = KiCadImporter().to_ir(FIXTURE.read_bytes())
    out = KiCadExporter().from_ir(doc)
    tree = parse(out.decode("utf-8"))
    assert tree[0] == "kicad_pcb"


def test_pad_positions_survive_roundtrip():
    from forgelab.spec import (
        NODE_BOARD,
        NODE_COMPONENT,
        BoardConstraints,
        DesignRules,
        DocumentMeta,
        Domain,
        ForgeDocument,
        Net,
        Node,
        Pad,
    )
    from forgelab.spec.version import SPEC_VERSION

    board = BoardConstraints(
        kicad_version="20240108",
        generator="forgelab",
        layers=[],
        outline=[],
        design_rules=DesignRules(clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4),
    )
    comp = Component(
        reference="U1",
        value="IC",
        footprint="Package_SO:SOIC-4",
        layer="F.Cu",
        at=[10.0, 20.0, 0.0],
        pads=[
            Pad(number="1", net="", at=[-1.5, -2.0]),
            Pad(number="2", net="", at=[1.5, -2.0]),
            Pad(number="3", net="", at=[1.5, 2.0]),
            Pad(number="4", net="", at=[-1.5, 2.0]),
        ],
    )
    nodes = [
        Node(id=NODE_BOARD, type=NODE_BOARD, props=board.model_dump()),
        Node(id="net:0", type="net", props=Net(code=0, name="").model_dump()),
        Node(id="U1", type=NODE_COMPONENT, props=comp.model_dump()),
    ]
    doc1 = ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.HARDWARE,
        meta=DocumentMeta(name="t", generator="test"),
        nodes=nodes,
    )
    doc2 = KiCadImporter().to_ir(KiCadExporter().from_ir(doc1))
    pads2 = next(
        Component.model_validate(n.props).pads for n in doc2.nodes if n.type == NODE_COMPONENT
    )
    assert [p.at for p in pads2] == [[-1.5, -2.0], [1.5, -2.0], [1.5, 2.0], [-1.5, 2.0]]
