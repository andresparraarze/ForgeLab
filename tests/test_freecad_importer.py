import pytest

from forgelab.formats import FcDocument, FcObject, FcProperty, write_fcstd
from forgelab.importers.mechanical import FreeCADImporter, FreeCADParseError


def _box_fcstd():
    objects = [
        FcObject("Part", "App::Part", [FcProperty("name", "String", "Part")]),
        FcObject(
            "Body",
            "PartDesign::Body",
            [FcProperty("name", "String", "Body"), FcProperty("part", "Link", "Part")],
        ),
        FcObject(
            "Pad",
            "PartDesign::Pad",
            [
                FcProperty("name", "String", "Pad"),
                FcProperty("body", "Link", "Body"),
                FcProperty("profile", "Link", "Sketch"),
                FcProperty("length", "Float", 10.0),
            ],
        ),
    ]
    return write_fcstd(FcDocument(objects=objects, name="box", generator="forgelab-freecad"))


def test_import_maps_objects_to_nodes_in_order():
    doc = FreeCADImporter().to_ir(_box_fcstd())
    assert doc.domain.value == "mechanical"
    assert [(n.id, n.type) for n in doc.nodes] == [
        ("Part", "part"),
        ("Body", "body"),
        ("Pad", "pad"),
    ]
    assert doc.meta.name == "box"


def test_import_preserves_link_props_and_values():
    doc = FreeCADImporter().to_ir(_box_fcstd())
    pad = next(n for n in doc.nodes if n.id == "Pad")
    assert pad.props["body"] == "Body"
    assert pad.props["profile"] == "Sketch"
    assert pad.props["length"] == 10.0


def test_unknown_object_type_raises():
    bad = write_fcstd(FcDocument(objects=[FcObject("X", "App::Mystery", [])]))
    with pytest.raises(FreeCADParseError):
        FreeCADImporter().to_ir(bad)


def test_not_a_zip_raises_parse_error():
    with pytest.raises(FreeCADParseError):
        FreeCADImporter().to_ir(b"garbage")


def test_invalid_props_raise_parse_error():
    bad = write_fcstd(
        FcDocument(
            objects=[FcObject("Pad", "PartDesign::Pad", [FcProperty("name", "String", "Pad")])]
        )
    )
    with pytest.raises(FreeCADParseError):
        FreeCADImporter().to_ir(bad)


def test_import_handles_sketch_and_pocket_types():
    objects = [
        FcObject(
            "Sketch",
            "Sketcher::SketchObject",
            [
                FcProperty("name", "String", "Sketch"),
                FcProperty(
                    "geometry",
                    "GeometryList",
                    [{"geo_type": "circle", "points": [], "center": [0.0, 0.0], "radius": 4.0}],
                ),
                FcProperty(
                    "constraints",
                    "ConstraintList",
                    [{"ctype": "Radius", "value": 4.0, "name": ""}],
                ),
            ],
        ),
        FcObject(
            "Pocket",
            "PartDesign::Pocket",
            [
                FcProperty("name", "String", "Pocket"),
                FcProperty("profile", "Link", "Sketch"),
                FcProperty("through_all", "Bool", True),
            ],
        ),
    ]
    doc = FreeCADImporter().to_ir(write_fcstd(FcDocument(objects=objects)))
    assert [(n.id, n.type) for n in doc.nodes] == [("Sketch", "sketch"), ("Pocket", "pocket")]
    assert doc.nodes[0].props["geometry"][0]["radius"] == 4.0
    assert doc.nodes[1].props["through_all"] is True
