"""FreeCAD .FCStd exporter from ForgeLab IR.

Writes an archive FreeCAD genuinely opens:

- ``Document.xml`` — real FreeCAD schema (App::Part, PartDesign::Body,
  Sketcher::SketchObject with GeomLineSegment/GeomCircle, PartDesign::Pad,
  PartDesign::Pocket). Shapes carry no ``.brp`` files; a single Refresh
  (recompute) on open builds them from the parametric definitions.
- ``GuiDocument.xml`` — view providers that show each body + its tip feature
  shaded and hide intermediate features, sketches and origin datums (otherwise
  FreeCAD's defaults render the solids as wireframe-only).
- ``ForgeLab.Document.xml`` — the full ForgeLab property dialect (sidecar).
  FreeCAD ignores unknown archive entries; the importer prefers this entry,
  which is what preserves the exact IR round-trip identity (the real schema
  cannot carry e.g. constraint metadata losslessly).
"""

import xml.etree.ElementTree as ET

from forgelab.exporters.base import Exporter
from forgelab.exporters.mechanical.realxml import (
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
    NODE_BOOLEAN,
    NODE_FILLET,
    NODE_LOFT,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_REVOLVE,
    NODE_SHELL,
    NODE_SKETCH,
    NODE_SWEEP,
    Body,
    Boolean,
    Fillet,
    Loft,
    Pad,
    Part,
    Pocket,
    Revolve,
    Shell,
    Sketch,
    Sweep,
)
from forgelab.sync.hashing import document_hash

_FCTYPE_BY_NODE = {
    NODE_PART: "App::Part",
    NODE_BODY: "PartDesign::Body",
    NODE_SKETCH: "Sketcher::SketchObject",
    NODE_PAD: "PartDesign::Pad",
    NODE_POCKET: "PartDesign::Pocket",
    NODE_LOFT: "Part::Loft",
    NODE_SWEEP: "Part::Sweep",
    NODE_FILLET: "Part::Fillet",
    NODE_SHELL: "Part::Thickness",
    NODE_REVOLVE: "Part::Revolution",
    # The sidecar is ForgeLab's own dialect, so it names the boolean family
    # rather than one concrete member: the real Document.xml picks
    # Part::MultiFuse / Part::MultiCommon / Part::Cut per operation.
    NODE_BOOLEAN: "Part::Boolean",
}

_MODEL_BY_NODE: dict[str, type[AnyModel]] = {
    NODE_PART: Part,
    NODE_BODY: Body,
    NODE_SKETCH: Sketch,
    NODE_PAD: Pad,
    NODE_POCKET: Pocket,
    NODE_LOFT: Loft,
    NODE_SWEEP: Sweep,
    NODE_FILLET: Fillet,
    NODE_SHELL: Shell,
    NODE_REVOLVE: Revolve,
    NODE_BOOLEAN: Boolean,
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
    NODE_LOFT: [
        ("name", "String"),
        ("body", "Link"),
        ("profiles", "StringList"),
        ("ruled", "Bool"),
        ("closed", "Bool"),
    ],
    NODE_SWEEP: [
        ("name", "String"),
        ("body", "Link"),
        ("profile", "Link"),
        ("path", "Link"),
        ("frenet", "Bool"),
    ],
    NODE_FILLET: [
        ("name", "String"),
        ("body", "Link"),
        ("target", "Link"),
        ("radius", "Float"),
        ("edges", "IntList"),
    ],
    NODE_SHELL: [
        ("name", "String"),
        ("body", "Link"),
        ("target", "Link"),
        ("thickness", "Float"),
        ("faces_to_remove", "IntList"),
    ],
    NODE_REVOLVE: [
        ("name", "String"),
        ("body", "Link"),
        ("profile", "Link"),
        ("axis", "String"),
        ("angle", "Float"),
    ],
    NODE_BOOLEAN: [
        ("name", "String"),
        ("body", "Link"),
        ("operation", "String"),
        ("base", "Link"),
        ("tools", "StringList"),
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
        # Walk the whole tree: agents express the part->body->feature hierarchy
        # either as a flat node list or by nesting via Node.children. Iterating
        # only document.nodes dropped every nested Body/Sketch/Pad/Pocket.
        for node in document.walk():
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
        # Stamp the source-document hash onto the sidecar's root <Document> so
        # verify_sync can later tell whether this file is still in sync.
        sidecar_xml = _stamp_hash(sidecar_xml, document_hash(document.model_dump(mode="json")))
        real = build_real_document_xml(items, document.meta.name)
        return write_archive(
            {
                "Document.xml": real.document_xml,
                "GuiDocument.xml": real.gui_document_xml,
                _SIDECAR: sidecar_xml,
                **real.files,
            }
        )


def _stamp_hash(document_xml: bytes, hash_value: str) -> bytes:
    """Set a ``Hash`` attribute on the sidecar's root ``Document`` element."""
    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError:
        return document_xml
    root.set("Hash", hash_value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
