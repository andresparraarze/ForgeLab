"""FreeCAD .FCStd exporter from ForgeLab IR."""

from forgelab.exporters.base import Exporter
from forgelab.formats import FcDocument, FcObject, FcProperty, write_fcstd
from forgelab.spec import ForgeDocument
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SKETCH,
)

_FCTYPE_BY_NODE = {
    NODE_PART: "App::Part",
    NODE_BODY: "PartDesign::Body",
    NODE_SKETCH: "Sketcher::SketchObject",
    NODE_PAD: "PartDesign::Pad",
    NODE_POCKET: "PartDesign::Pocket",
}

# field name -> property type, per node type, in canonical write order.
_FIELDS = {
    NODE_PART: [("name", "String"), ("placement", "Placement")],
    NODE_BODY: [("name", "String"), ("part", "Link"), ("placement", "Placement")],
    NODE_SKETCH: [
        ("name", "String"),
        ("body", "Link"),
        ("plane", "String"),
        ("placement", "Placement"),
        ("geometry", "GeometryList"),
        ("constraints", "ConstraintList"),
    ],
    NODE_PAD: [
        ("name", "String"),
        ("body", "Link"),
        ("profile", "Link"),
        ("length", "Float"),
        ("reversed", "Bool"),
        ("midplane", "Bool"),
    ],
    NODE_POCKET: [
        ("name", "String"),
        ("body", "Link"),
        ("profile", "Link"),
        ("length", "Float"),
        ("through_all", "Bool"),
        ("reversed", "Bool"),
        ("midplane", "Bool"),
    ],
}

assert set(_FCTYPE_BY_NODE) == set(_FIELDS), "FreeCAD export maps are out of sync"


class FreeCADExporter(Exporter):
    """Export ForgeLab mechanical IR to a FreeCAD .FCStd file."""

    tool_name = "freecad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        objects: list[FcObject] = []
        for node in document.nodes:
            fc_type = _FCTYPE_BY_NODE.get(node.type)
            if fc_type is None:
                raise ValueError(f"Cannot export node type {node.type!r} to FreeCAD")
            properties = [
                FcProperty(name=field_name, ptype=ptype, value=node.props[field_name])
                for field_name, ptype in _FIELDS[node.type]
            ]
            objects.append(FcObject(name=node.id, obj_type=fc_type, properties=properties))
        fc_doc = FcDocument(
            objects=objects,
            name=document.meta.name,
            generator=document.meta.generator or "forgelab-freecad",
        )
        return write_fcstd(fc_doc)
