from pathlib import Path

from forgelab.exporters.mechanical import FreeCADExporter
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.spec.mechanical import (
    Body,
    Constraint,
    Pad,
    Part,
    Pocket,
    Sketch,
    SketchGeometry,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "mechanical"


def _box_with_hole_doc():
    part = Part(name="Part")
    body = Body(name="Body", part="Part")
    base = Sketch(
        name="Sketch",
        body="Body",
        plane="XY_Plane",
        geometry=[
            SketchGeometry(geo_type="line", points=[0.0, 0.0, 40.0, 0.0]),
            SketchGeometry(geo_type="line", points=[40.0, 0.0, 40.0, 20.0]),
            SketchGeometry(geo_type="line", points=[40.0, 20.0, 0.0, 20.0]),
            SketchGeometry(geo_type="line", points=[0.0, 20.0, 0.0, 0.0]),
        ],
        constraints=[
            Constraint(ctype="DistanceX", value=40.0, name="Width"),
            Constraint(ctype="DistanceY", value=20.0, name="Depth"),
        ],
    )
    pad = Pad(name="Pad", body="Body", profile="Sketch", length=10.0)
    hole_sketch = Sketch(
        name="Sketch001",
        body="Body",
        plane="XY_Plane",
        geometry=[SketchGeometry(geo_type="circle", center=[20.0, 10.0], radius=4.0)],
        constraints=[Constraint(ctype="Radius", value=4.0, name="HoleRadius")],
    )
    pocket = Pocket(
        name="Pocket", body="Body", profile="Sketch001", through_all=True, reversed=True
    )
    pairs = [
        (part, "part"),
        (body, "body"),
        (base, "sketch"),
        (pad, "pad"),
        (hole_sketch, "sketch"),
        (pocket, "pocket"),
    ]
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="box-with-hole", generator="forgelab-freecad"),
        nodes=[Node(id=m.name, type=t, props=m.model_dump()) for m, t in pairs],
    )


def test_roundtrip_is_identity():
    doc = _box_with_hole_doc()
    data = FreeCADExporter().from_ir(doc)
    assert FreeCADImporter().to_ir(data) == doc


def test_roundtrip_is_stable_twice():
    doc = _box_with_hole_doc()
    once = FreeCADExporter().from_ir(doc)
    twice = FreeCADExporter().from_ir(FreeCADImporter().to_ir(once))
    assert once == twice


def test_example_files_match_generated():
    doc = _box_with_hole_doc()
    fcstd_bytes = (EXAMPLES / "box-with-hole.FCStd").read_bytes()
    assert FreeCADImporter().to_ir(fcstd_bytes) == doc
