import zipfile
from io import BytesIO

import pytest

from forgelab.formats import (
    FcDocument,
    FcObject,
    FcProperty,
    FcstdError,
    read_document,
    read_objects,
    write_fcstd,
)


def _sample_document():
    return FcDocument(
        name="doc",
        generator="forgelab-freecad",
        objects=[
            FcObject(
                name="Pad",
                obj_type="PartDesign::Pad",
                properties=[
                    FcProperty("name", "String", "Pad"),
                    FcProperty("profile", "Link", "Sketch"),
                    FcProperty("length", "Float", 10.0),
                    FcProperty("reversed", "Bool", False),
                ],
            ),
            FcObject(
                name="Body",
                obj_type="PartDesign::Body",
                properties=[
                    FcProperty(
                        "placement",
                        "Placement",
                        {"position": [1.0, 2.0, 3.0], "rotation": [0.0, 0.0, 0.0, 1.0]},
                    ),
                ],
            ),
            FcObject(
                name="Sketch",
                obj_type="Sketcher::SketchObject",
                properties=[
                    FcProperty(
                        "geometry",
                        "GeometryList",
                        [
                            {
                                "geo_type": "line",
                                "points": [0.0, 0.0, 40.0, 0.0],
                                "center": [],
                                "radius": 0.0,
                            },
                            {
                                "geo_type": "circle",
                                "points": [],
                                "center": [20.0, 10.0],
                                "radius": 4.0,
                            },
                        ],
                    ),
                    FcProperty(
                        "constraints",
                        "ConstraintList",
                        [{"ctype": "DistanceX", "value": 40.0, "name": "w"}],
                    ),
                ],
            ),
        ],
    )


def test_roundtrip_preserves_everything():
    doc = _sample_document()
    restored = read_document(write_fcstd(doc))
    assert restored == doc


def test_read_objects_is_objects_only():
    doc = _sample_document()
    objs = read_objects(write_fcstd(doc))
    assert [o.name for o in objs] == ["Pad", "Body", "Sketch"]


def test_output_is_a_zip_with_document_xml():
    data = write_fcstd(_sample_document())
    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert "Document.xml" in zf.namelist()


def test_write_is_byte_stable():
    doc = _sample_document()
    assert write_fcstd(doc) == write_fcstd(doc)


def test_not_a_zip_raises():
    with pytest.raises(FcstdError):
        read_document(b"not a zip")


def test_missing_document_xml_raises():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Other.xml", "<x/>")
    with pytest.raises(FcstdError):
        read_document(buffer.getvalue())


def test_malformed_xml_raises():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Document.xml", "<Document><not closed>")
    with pytest.raises(FcstdError):
        read_document(buffer.getvalue())


def test_unsupported_property_type_raises_on_write():
    doc = FcDocument(objects=[FcObject("X", "App::Part", [FcProperty("p", "Mystery", 1)])])
    with pytest.raises(FcstdError):
        write_fcstd(doc)


def test_integer_property_roundtrips():
    doc = FcDocument(objects=[FcObject("X", "App::Part", [FcProperty("count", "Integer", 7)])])
    restored = read_document(write_fcstd(doc))
    assert restored.objects[0].properties[0].value == 7


def test_empty_document_roundtrips():
    doc = FcDocument(name="empty")
    assert read_document(write_fcstd(doc)) == doc


def test_malformed_placement_raises_on_write():
    doc = FcDocument(
        objects=[
            FcObject(
                "B",
                "PartDesign::Body",
                [
                    FcProperty(
                        "placement",
                        "Placement",
                        {"position": [0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0]},
                    )
                ],
            )
        ]
    )
    with pytest.raises(FcstdError):
        write_fcstd(doc)


def test_unsupported_property_type_raises_on_read():
    xml = (
        "<Document SchemaVersion='4' DocName='' DocGenerator=''>"
        "<Objects Count='1'><Object type='App::Part' name='X'/></Objects>"
        "<ObjectData Count='1'><Object name='X'><Properties Count='1'>"
        "<Property name='p' type='Mystery' value='1'/>"
        "</Properties></Object></ObjectData></Document>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Document.xml", xml)
    with pytest.raises(FcstdError):
        read_document(buffer.getvalue())
