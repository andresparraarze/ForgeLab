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


def _sidecar_fcstd(*, sketch_body: str, body_id: str, body_name: str) -> bytes:
    """A sidecar-format FCStd: a Part/Body/Sketch(XY_Plane)/Pad in the
    ForgeLab.Document.xml dialect, with the sketch referencing its body however
    the caller specifies (by id, by label, or blank)."""
    import io
    import zipfile

    from forgelab.formats import write_archive
    from forgelab.formats.fcstd import FcDocument, FcObject, FcProperty, write_fcstd

    objects = [
        FcObject("Part", "App::Part", [FcProperty("name", "String", "Part")]),
        FcObject(
            body_id,
            "PartDesign::Body",
            [FcProperty("name", "String", body_name), FcProperty("part", "Link", "Part")],
        ),
        FcObject(
            "Sketch",
            "Sketcher::SketchObject",
            [
                FcProperty("name", "String", "Sketch"),
                FcProperty("body", "Link", sketch_body),
                FcProperty("plane", "String", "XY_Plane"),
                FcProperty(
                    "placement", "Placement", {"position": [0, 0, 0], "rotation": [0, 0, 0, 1]}
                ),
                FcProperty(
                    "geometry",
                    "GeometryList",
                    [{"geo_type": "circle", "center": [0.0, 0.0], "radius": 4.0}],
                ),
                FcProperty("constraints", "ConstraintList", []),
            ],
        ),
        FcObject(
            "Pad",
            "PartDesign::Pad",
            [
                FcProperty("name", "String", "Pad"),
                FcProperty("body", "Link", sketch_body),
                FcProperty("profile", "Link", "Sketch"),
                FcProperty("length", "Float", 10.0),
                FcProperty("reversed", "Bool", False),
                FcProperty("midplane", "Bool", False),
            ],
        ),
    ]
    sidecar = zipfile.ZipFile(io.BytesIO(write_fcstd(FcDocument(objects, "doc", "gen")))).read(
        "Document.xml"
    )
    return write_archive({"Document.xml": b"<Document/>", "ForgeLab.Document.xml": sidecar})


def _exported_attachment_support(data: bytes) -> bool:
    import io
    import zipfile

    doc = FreeCADImporter().to_ir(data)
    # The sidecar must carry plane='XY_Plane' through to the imported sketch.
    assert all(n.props["plane"] == "XY_Plane" for n in doc.nodes if n.type == "sketch")
    real = zipfile.ZipFile(io.BytesIO(FreeCADExporter().from_ir(doc))).read("Document.xml").decode()
    return "AttachmentSupport" in real


def test_sidecar_xy_plane_sketch_keeps_attachment_support():
    # Round-trip: a sidecar-format FCStd with an XY_Plane sketch must re-export
    # with AttachmentSupport in the real Document.xml — even when the sketch
    # references its body by label or leaves the reference blank.
    assert _exported_attachment_support(
        _sidecar_fcstd(sketch_body="Body", body_id="Body", body_name="Body")
    )
    assert _exported_attachment_support(
        _sidecar_fcstd(sketch_body="MotorBody", body_id="Body", body_name="MotorBody")
    )
    assert _exported_attachment_support(
        _sidecar_fcstd(sketch_body="", body_id="Body", body_name="Body")
    )
