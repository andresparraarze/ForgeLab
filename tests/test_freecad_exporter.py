import pytest

from forgelab.exporters.mechanical import FreeCADExporter
from forgelab.formats import read_document
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.spec.mechanical import Body, Pad, Part


def _doc():
    part = Part(name="Part")
    body = Body(name="Body", part="Part")
    pad = Pad(name="Pad", body="Body", profile="Sketch", length=10.0)
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="box", generator="forgelab-freecad"),
        nodes=[
            Node(id="Part", type="part", props=part.model_dump()),
            Node(id="Body", type="body", props=body.model_dump()),
            Node(id="Pad", type="pad", props=pad.model_dump()),
        ],
    )


def test_export_produces_readable_fcstd():
    data = FreeCADExporter().from_ir(_doc())
    fc_doc = read_document(data, member="ForgeLab.Document.xml")
    assert fc_doc.name == "box"
    assert [(o.name, o.obj_type) for o in fc_doc.objects] == [
        ("Part", "App::Part"),
        ("Body", "PartDesign::Body"),
        ("Pad", "PartDesign::Pad"),
    ]


def test_exported_pad_carries_length_and_links():
    data = FreeCADExporter().from_ir(_doc())
    fc_doc = read_document(data, member="ForgeLab.Document.xml")
    pad = next(o for o in fc_doc.objects if o.name == "Pad")
    by_name = {p.name: p for p in pad.properties}
    assert by_name["length"].value == 10.0
    assert by_name["profile"].value == "Sketch"
    assert by_name["profile"].ptype == "Link"


def test_export_is_byte_stable():
    doc = _doc()
    assert FreeCADExporter().from_ir(doc) == FreeCADExporter().from_ir(doc)


def test_unknown_node_type_raises():
    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="x"),
        nodes=[Node(id="weird", type="wormhole", props={})],
    )
    with pytest.raises(ValueError):
        FreeCADExporter().from_ir(doc)


def test_archive_contains_real_schema_gui_and_sidecar():
    import zipfile
    from io import BytesIO
    from pathlib import Path

    from forgelab.sdk import load

    example = load(Path("examples/mechanical/box-with-hole.forge.json").read_text())
    data = FreeCADExporter().from_ir(example)
    archive = zipfile.ZipFile(BytesIO(data))
    names = archive.namelist()
    assert names[0] == "Document.xml"  # FreeCAD reads the archive sequentially
    assert "GuiDocument.xml" in names
    assert "ForgeLab.Document.xml" in names
    real = archive.read("Document.xml").decode()
    assert "PartDesign::Body" in real
    assert "Part::GeomLineSegment" in real
    assert "App::PropertyPlacement" in real
    assert 'Property name="Tip"' in real
    assert "BaseFeature" in real  # pocket cuts need the base link


def test_export_body_without_optional_part_does_not_keyerror():
    from forgelab.spec import SPEC_VERSION, ForgeDocument

    doc = ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "mechanical",
            "meta": {"name": "sparse", "generator": "test"},
            "nodes": [{"id": "B", "type": "body", "props": {"name": "B"}}],
        }
    )
    data = FreeCADExporter().from_ir(doc)  # must not raise KeyError('part')
    assert data[:2] == b"PK"


def test_objects_are_marked_touched_for_recompute_on_open():
    # Without stored .brp shapes, FreeCAD only rebuilds geometry for objects
    # marked dirty; Touched="1" makes a plain doc.recompute() do the work.
    import re
    import zipfile
    from io import BytesIO

    data = FreeCADExporter().from_ir(_doc())
    real = zipfile.ZipFile(BytesIO(data)).read("Document.xml").decode()
    decls = re.findall(r"<Object type=\"[^\"]+\"[^>]*/>", real)
    assert decls
    assert all('Touched="1"' in d for d in decls)


def test_non_xy_sketch_gets_attachment_and_real_rotation():
    # Bug fix: sketches on a non-XY plane must attach to the body's datum plane
    # (FreeCAD ignores a plain Placement on an in-body sketch) and the rotation
    # must be written into the axis-angle form FreeCAD actually reads.
    import zipfile
    from io import BytesIO

    from forgelab.spec import SPEC_VERSION, ForgeDocument
    from forgelab.spec.mechanical import Body, Sketch, SketchGeometry

    doc = ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "mechanical",
            "meta": {"name": "v", "generator": "test"},
            "nodes": [
                {"id": "Body", "type": "body", "props": Body(name="Body").model_dump()},
                {
                    "id": "S",
                    "type": "sketch",
                    "props": Sketch(
                        name="S",
                        body="Body",
                        plane="XZ_Plane",
                        geometry=[SketchGeometry(geo_type="circle", center=[0, 0], radius=2.0)],
                    ).model_dump(),
                },
            ],
        }
    )
    real = zipfile.ZipFile(BytesIO(FreeCADExporter().from_ir(doc))).read("Document.xml").decode()
    # The body owns an origin the sketch can attach to.
    assert 'name="Body_XZ_Plane"' in real
    assert 'name="Body_Origin"' in real
    # The sketch attaches FlatFace to the body's XZ plane.
    assert '<Link obj="Body_XZ_Plane" sub=""/>' in real
    assert 'name="MapMode"' in real
    # The XZ quaternion is written with a consistent, non-identity axis-angle
    # (the bug was a hardcoded A="0" that flattened every rotation).
    assert 'Q0="0.7071067811865475"' in real
    assert 'A="1.5707963267948966"' in real
    sketch_block = real.split('name="S"')[1].split("</Object>")[0]
    assert 'A="0.0000000000000000" Ox="0.0000000000000000"' not in sketch_block


def _sketch_doc(plane: str):
    from forgelab.spec import SPEC_VERSION, ForgeDocument
    from forgelab.spec.mechanical import Body, Sketch, SketchGeometry

    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "mechanical",
            "meta": {"name": "v", "generator": "test"},
            "nodes": [
                {"id": "Body", "type": "body", "props": Body(name="Body").model_dump()},
                {
                    "id": "S",
                    "type": "sketch",
                    "props": Sketch(
                        name="S",
                        body="Body",
                        plane=plane,
                        geometry=[SketchGeometry(geo_type="circle", center=[0, 0], radius=2.0)],
                    ).model_dump(),
                },
            ],
        }
    )


@pytest.mark.parametrize(
    ("plane", "datum"),
    [
        ("XY_Plane", "Body_XY_Plane"),
        ("XY", "Body_XY_Plane"),
        ("xy", "Body_XY_Plane"),
        ("Top", "Body_XY_Plane"),
        ("XZ_Plane", "Body_XZ_Plane"),
        ("XZ", "Body_XZ_Plane"),
        ("Front", "Body_XZ_Plane"),
        ("YZ", "Body_YZ_Plane"),
        ("Right", "Body_YZ_Plane"),
        ("", "Body_XY_Plane"),  # unknown / empty falls back to XY
        ("totally-bogus", "Body_XY_Plane"),
    ],
)
def test_attachment_support_emitted_for_any_plane_spelling(plane, datum):
    # Bug: AttachmentSupport was gated on plane being one of the exact strings
    # XY_Plane/XZ_Plane/YZ_Plane, so an agent writing "XY", "Front", etc. got a
    # sketch with NO attachment — it never oriented and the geometry never
    # rendered. Every sketch with a body must attach to a datum plane.
    import zipfile
    from io import BytesIO

    real = (
        zipfile.ZipFile(BytesIO(FreeCADExporter().from_ir(_sketch_doc(plane))))
        .read("Document.xml")
        .decode()
    )
    assert "AttachmentSupport" in real
    assert f'<Link obj="{datum}" sub=""/>' in real
    assert 'name="MapMode"' in real
