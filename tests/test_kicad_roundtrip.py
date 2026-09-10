from pathlib import Path

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.formats import parse
from forgelab.importers.hardware.kicad import KiCadImporter
from forgelab.spec import NODE_COMPONENT, NODE_NET, SPEC_VERSION, Component, ForgeDocument

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "hardware" / "blinky.kicad_pcb"


def test_semantic_roundtrip_reaches_a_fixed_point():
    """A round trip normalizes to the library's geometry, then stops moving.

    This used to assert plain identity, and could, because export was a faithful
    echo of whatever the IR said — including pad geometry that was invented. Now
    a component naming a stock KiCad footprint is exported with the library's
    real copper, so the first round trip *corrects* the document rather than
    reproducing it: the fixture's two pads at (0 0) come back at the 0603
    footprint's actual +/-0.825mm.

    Identity is therefore the wrong property to pin; convergence is the right
    one. One pass may change the document, and every pass after it must not.
    """
    imp = KiCadImporter()
    exp = KiCadExporter()
    doc1 = imp.to_ir(FIXTURE.read_bytes())
    doc2 = imp.to_ir(exp.from_ir(doc1))
    doc3 = imp.to_ir(exp.from_ir(doc2))
    assert doc2 == doc3


def test_export_is_byte_identical_once_the_document_has_settled():
    """export -> import -> export stops changing the file.

    The property that matters for `verify_sync` and for diffing a board against
    its native file: a round trip must not keep rewriting the bytes on disk.

    The *first* export of a freshly imported board legitimately differs from the
    second, and only in the embedded `forgelab_hash`: that hash is taken over the
    document, and the first round trip corrects the document's pad geometry to
    the library's. From the fixed point onward the bytes must be identical —
    which also means the hash has stopped moving, so `verify_sync` cannot report
    a board as drifted just for having been round-tripped.
    """
    imp = KiCadImporter()
    exp = KiCadExporter()
    settled = imp.to_ir(exp.from_ir(imp.to_ir(FIXTURE.read_bytes())))
    once = exp.from_ir(settled)
    twice = exp.from_ir(imp.to_ir(once))
    assert once == twice


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


# ----------------------------------------- everything the importer used to drop


def _full_board() -> ForgeDocument:
    """A board carrying every feature the exporter can write.

    The round-trip tests were passing while the importer silently discarded
    drills, tracks, vias and copper pours, because the only fixture was a bare
    two-footprint board that had none of them. Measured on the routed Arduino
    Uno, a single round trip lost 32 drills and every routed track: a
    through-hole board came back surface-mount and unrouted.
    """
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "full", "generator": "test"},
            "nodes": [
                {
                    "id": "board",
                    "type": "board",
                    "props": {
                        "kicad_version": "20240108",
                        "generator": "pcbnew",
                        "layers": [
                            {"ordinal": 0, "canonical_name": "F.Cu", "layer_type": "signal"},
                            {"ordinal": 31, "canonical_name": "B.Cu", "layer_type": "signal"},
                            {"ordinal": 44, "canonical_name": "Edge.Cuts", "layer_type": "user"},
                        ],
                        # Three straight sides and one rounded corner, so the arc
                        # path is exercised and the mirror axis has to account
                        # for a point that is on no straight segment.
                        "outline": [
                            {"start": [0, 0], "end": [30, 0]},
                            {"start": [30, 0], "end": [30, 16]},
                            {"start": [30, 16], "end": [4, 20], "arc_mid": [18, 19]},
                            {"start": [4, 20], "end": [0, 0]},
                        ],
                        "design_rules": {
                            "clearance": 0.2,
                            "track_width": 0.25,
                            "via_diameter": 0.8,
                            "via_drill": 0.4,
                        },
                    },
                },
                {"id": "net:0", "type": "net", "props": {"code": 0, "name": ""}},
                {"id": "net:1", "type": "net", "props": {"code": 1, "name": "GND"}},
                {"id": "net:2", "type": "net", "props": {"code": 2, "name": "VCC"}},
                {
                    "id": "J1",
                    "type": "component",
                    "props": {
                        "reference": "J1",
                        "value": "CONN",
                        "footprint": "NotAReal:Header",
                        "layer": "F.Cu",
                        "at": [8, 8, 0],
                        "pads": [
                            {
                                "number": "1",
                                "net": "GND",
                                "at": [0, 0],
                                "size": [1.7, 1.7],
                                "shape": "rect",
                                "drill": {"diameter": 1.0},
                            },
                            {
                                "number": "2",
                                "net": "VCC",
                                "at": [2.54, 0],
                                "size": [1.7, 1.7],
                                "shape": "oval",
                                "drill": {"oval": [1.2, 0.6], "plated": False},
                            },
                        ],
                    },
                },
                {
                    "id": "track_1",
                    "type": "track",
                    "props": {
                        "net": "VCC",
                        "layer": "F.Cu",
                        "start": [10.54, 8],
                        "end": [20, 8],
                        "width": 0.25,
                    },
                },
                {
                    "id": "via_1",
                    "type": "via",
                    "props": {"at": [20, 8], "net": "VCC", "size": 0.8, "drill": 0.4},
                },
                {
                    "id": "zone_1",
                    "type": "zone",
                    "props": {
                        "net": "GND",
                        "layer": "B.Cu",
                        "polygon": [[2, 2], [28, 2], [28, 14], [2, 14]],
                        "min_thickness": 0.25,
                    },
                },
            ],
        }
    )


def _types(doc):
    counts = {}
    for node in doc.walk():
        counts[node.type] = counts.get(node.type, 0) + 1
    return counts


def test_a_full_board_survives_import_intact():
    doc = _full_board()
    back = KiCadImporter().to_ir(KiCadExporter().from_ir(doc))
    before, after = _types(doc), _types(back)
    for kind in ("track", "via", "zone", "component", "board"):
        assert after.get(kind) == before.get(kind), f"{kind}: {before} -> {after}"


def test_through_hole_drills_survive_import():
    """Every header, DIP and connector came back surface-mount without this."""
    back = KiCadImporter().to_ir(KiCadExporter().from_ir(_full_board()))
    comp = next(n for n in back.walk() if n.type == NODE_COMPONENT)
    drills = {p["number"]: p.get("drill") for p in comp.props["pads"]}
    assert drills["1"]["diameter"] == 1.0
    assert drills["1"]["plated"] is True
    assert drills["2"]["oval"] == [1.2, 0.6]
    assert drills["2"]["plated"] is False, "an unplated hole must not come back plated"


def test_a_curved_outline_keeps_its_curve():
    back = KiCadImporter().to_ir(KiCadExporter().from_ir(_full_board()))
    board = next(n for n in back.walk() if n.type == "board")
    arcs = [seg for seg in board.props["outline"] if seg.get("arc_mid")]
    assert len(arcs) == 1
    assert arcs[0]["arc_mid"] == [18.0, 19.0]


def test_a_full_board_export_is_byte_identical_after_a_roundtrip():
    """The property the old fixture was too thin to test."""
    exp, imp = KiCadExporter(), KiCadImporter()
    once = exp.from_ir(imp.to_ir(exp.from_ir(_full_board())))
    twice = exp.from_ir(imp.to_ir(once))
    assert once == twice


def test_an_imported_board_is_named_after_its_file():
    """Every imported board used to come back called "blinky"."""
    imp = KiCadImporter()
    imp.source_name = "power_supply"
    doc = imp.to_ir(KiCadExporter().from_ir(_full_board()))
    assert doc.meta.name == "power_supply"


def test_a_generator_containing_a_space_still_parses():
    """It was written as a bare symbol, which a space splits into two tokens."""
    doc = _full_board()
    board = next(n for n in doc.nodes if n.type == "board")
    board.props["generator"] = "ForgeLab 0.2"
    text = KiCadExporter().from_ir(doc).decode()
    assert KiCadImporter().to_ir(text.encode()) is not None
