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
    fc_doc = read_document(data)
    assert fc_doc.name == "box"
    assert [(o.name, o.obj_type) for o in fc_doc.objects] == [
        ("Part", "App::Part"),
        ("Body", "PartDesign::Body"),
        ("Pad", "PartDesign::Pad"),
    ]


def test_exported_pad_carries_length_and_links():
    data = FreeCADExporter().from_ir(_doc())
    fc_doc = read_document(data)
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
