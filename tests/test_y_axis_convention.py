"""The hardware IR's Y-axis convention, pinned concretely.

Normative (forgelab.spec.hardware): IR coordinates are millimetres in a Y-up
frame, origin at the board outline's lower-left corner, rotation degrees
counterclockwise. KiCad files are Y-down, so its exporter mirrors absolute Y
about the outline's vertical centre and negates pad-local offsets; Gerber is
natively Y-up and passes coordinates through unchanged. These tests assert
specific numbers on both sides so a regression in either exporter's frame
handling fails immediately instead of needing another audit to notice.
"""

import zipfile
from io import BytesIO

from forgelab.exporters.hardware.gerber import GerberExporter
from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.formats import parse
from forgelab.importers.hardware.kicad import KiCadImporter
from forgelab.spec import SPEC_VERSION, ForgeDocument

# Board outline: (0,0) to (30,20), so the KiCad mirror axis is ymin+ymax = 20.
_W, _H = 30.0, 20.0


def _doc() -> ForgeDocument:
    corners = [(0.0, 0.0), (_W, 0.0), (_W, _H), (0.0, _H)]
    outline = [{"start": list(corners[i]), "end": list(corners[(i + 1) % 4])} for i in range(4)]
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "y-convention", "generator": "test"},
            "nodes": [
                {
                    "id": "board",
                    "type": "board",
                    "props": {
                        "kicad_version": "20240108",
                        "generator": "test",
                        "outline": outline,
                        "design_rules": {
                            "clearance": 0.2,
                            "track_width": 0.25,
                            "via_diameter": 0.8,
                            "via_drill": 0.4,
                        },
                    },
                },
                {"id": "net_sig", "type": "net", "props": {"code": 1, "name": "SIG"}},
                {
                    "id": "R1",
                    "type": "component",
                    "props": {
                        "reference": "R1",
                        "value": "1k",
                        "footprint": "R_0603",
                        "layer": "F.Cu",
                        # IR position (10, 5): 10mm from the left edge, 5mm UP
                        # from the bottom edge (Y-up, origin lower-left).
                        "at": [10.0, 5.0, 0.0],
                        "pads": [
                            # Pad 1mm ABOVE the component origin in IR terms.
                            {
                                "number": "1",
                                "net": "SIG",
                                "at": [0.0, 1.0],
                                "size": [0.9, 1.0],
                            }
                        ],
                    },
                },
                {
                    "id": "track_1",
                    "type": "track",
                    "props": {
                        "net": "SIG",
                        "layer": "F.Cu",
                        "start": [1.0, 2.0],
                        "end": [3.0, 2.0],
                        "width": 0.25,
                    },
                },
                {
                    "id": "via_1",
                    "type": "via",
                    "props": {"at": [4.0, 6.0], "net": "SIG", "size": 0.8, "drill": 0.4},
                },
            ],
        }
    )


def _blocks(tree, tag):
    return [e for e in tree if isinstance(e, list) and e and str(e[0]) == tag]


def _sub(block, tag):
    return next(e for e in block if isinstance(e, list) and e and str(e[0]) == tag)


def test_kicad_export_flips_y_into_kicads_y_down_frame():
    tree = parse(KiCadExporter().from_ir(_doc()).decode())
    # Component: IR (10, 5) on a 0..20 board -> KiCad (10, 20 - 5) = (10, 15).
    (fp,) = _blocks(tree, "footprint")
    assert _sub(fp, "at")[1:4] == [10, 15, 0]
    # Pad-local offset: IR (0, +1) = up -> KiCad (0, -1) (Y-down local frame).
    (pad,) = [e for e in fp if isinstance(e, list) and str(e[0]) == "pad"]
    assert _sub(pad, "at")[1:3] == [0, -1]
    # Track: IR y=2 -> KiCad y=18 at both endpoints.
    (segment,) = _blocks(tree, "segment")
    assert _sub(segment, "start")[1:3] == [1, 18]
    assert _sub(segment, "end")[1:3] == [3, 18]
    # Via: IR (4, 6) -> KiCad (4, 14).
    (via,) = _blocks(tree, "via")
    assert _sub(via, "at")[1:3] == [4, 14]
    # Outline: the bottom edge (IR y=0) becomes KiCad y=20.
    lines = _blocks(tree, "gr_line")
    endpoints = {(float(_sub(li, "start")[1]), float(_sub(li, "start")[2])) for li in lines} | {
        (float(_sub(li, "end")[1]), float(_sub(li, "end")[2])) for li in lines
    }
    assert (0.0, 20.0) in endpoints and (30.0, 0.0) in endpoints


def test_gerber_export_passes_y_up_through_unflipped():
    archive = zipfile.ZipFile(BytesIO(GerberExporter().from_ir(_doc())))
    fcu = archive.read("F_Cu.gbr").decode()
    # Pad flash at the absolute IR position (10, 5) + (0, 1) = (10, 6): no flip.
    assert "X10000000Y6000000D03*" in fcu
    # Track endpoints exactly as in the IR.
    assert "X1000000Y2000000D02*" in fcu
    assert "X3000000Y2000000D01*" in fcu
    # Via flash and drill hole at the IR position (4, 6).
    assert "X4000000Y6000000D03*" in fcu
    assert "X4.000Y6.000" in archive.read("drill.drl").decode()
    # Outline unflipped: the bottom edge stays at y=0.
    edge = archive.read("Edge_Cuts.gbr").decode()
    assert "X0Y0D02*" in edge or "X0Y0" in edge


def test_kicad_round_trip_is_identity_under_the_flip():
    doc1 = _doc()
    text = KiCadExporter().from_ir(doc1)
    doc2 = KiCadImporter().to_ir(text)
    comps = {n.id: n for n in doc2.nodes}
    r1 = next(n for n in doc2.nodes if n.type == "component")
    assert r1.props["at"] == [10.0, 5.0, 0.0]
    assert r1.props["pads"][0]["at"] == [0.0, 1.0]
    board = next(n for n in doc2.nodes if n.type == "board")
    ys = [p[1] for seg in board.props["outline"] for p in (seg["start"], seg["end"])]
    assert min(ys) == 0.0 and max(ys) == 20.0
    assert comps  # sanity
