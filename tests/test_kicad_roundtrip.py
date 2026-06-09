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
