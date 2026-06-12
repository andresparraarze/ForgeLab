"""FreeCAD .FCStd exporter from ForgeLab IR.

Writes an archive FreeCAD genuinely opens:

- ``Document.xml`` — real FreeCAD schema (App::Part, PartDesign::Body,
  Sketcher::SketchObject with GeomLineSegment/GeomCircle, PartDesign::Pad,
  PartDesign::Pocket). Shapes carry no ``.brp`` files; FreeCAD recomputes
  them from the parametric definitions on load.
- ``GuiDocument.xml`` — minimal view-provider stub.
- ``ForgeLab.Document.xml`` — the full ForgeLab property dialect (sidecar).
  FreeCAD ignores unknown archive entries; the importer prefers this entry,
  which is what preserves the exact IR round-trip identity (the real schema
  cannot carry e.g. constraint metadata losslessly).
"""

from forgelab.exporters.base import Exporter
from forgelab.exporters.mechanical.realxml import (
    GUI_DOCUMENT_XML,
    AnyModel,
    build_real_document_xml,
)
from forgelab.formats import (
    FcDocument,
    FcObject,
    FcProperty,
    read_archive_entry,
    write_archive,
    write_fcstd,
)
from forgelab.spec import ForgeDocument
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SKETCH,
    Body,
    Pad,
    Part,
    Pocket,
    Sketch,
)

_FCTYPE_BY_NODE = {
    NODE_PART: "App::Part",
    NODE_BODY: "PartDesign::Body",
    NODE_SKETCH: "Sketcher::SketchObject",
    NODE_PAD: "PartDesign::Pad",
    NODE_POCKET: "PartDesign::Pocket",
}

_MODEL_BY_NODE: dict[str, type[AnyModel]] = {
    NODE_PART: Part,
    NODE_BODY: Body,
    NODE_SKETCH: Sketch,
    NODE_PAD: Pad,
    NODE_POCKET: Pocket,
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

assert set(_FCTYPE_BY_NODE) == set(_FIELDS) == set(_MODEL_BY_NODE), (
    "FreeCAD export maps are out of sync"
)

_SIDECAR = "ForgeLab.Document.xml"


class FreeCADExporter(Exporter):
    """Export ForgeLab mechanical IR to a FreeCAD .FCStd file."""

    tool_name = "freecad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        objects: list[FcObject] = []
        items: list[tuple[str, str, AnyModel]] = []
        for node in document.nodes:
            fc_type = _FCTYPE_BY_NODE.get(node.type)
            if fc_type is None:
                raise ValueError(f"Cannot export node type {node.type!r} to FreeCAD")
            # Validate through the domain model so optional fields get their
            # defaults (a sparse hand-built node must not KeyError).
            model = _MODEL_BY_NODE[node.type].model_validate(node.props)
            props_full = model.model_dump()
            properties = [
                FcProperty(name=field_name, ptype=ptype, value=props_full[field_name])
                for field_name, ptype in _FIELDS[node.type]
            ]
            objects.append(FcObject(name=node.id, obj_type=fc_type, properties=properties))
            items.append((node.id, node.type, model))

        fc_doc = FcDocument(
            objects=objects,
            name=document.meta.name,
            generator=document.meta.generator or "forgelab-freecad",
        )
        # Reuse the dialect writer, then lift its Document.xml into the sidecar.
        sidecar_zip = write_fcstd(fc_doc)
        sidecar_xml = read_archive_entry(sidecar_zip, "Document.xml") or b""
        real_xml = build_real_document_xml(items, document.meta.name)
        return write_archive(
            {
                "Document.xml": real_xml,
                "GuiDocument.xml": GUI_DOCUMENT_XML,
                _SIDECAR: sidecar_xml,
            }
        )
