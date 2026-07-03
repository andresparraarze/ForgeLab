"""FreeCAD .FCStd importer -> ForgeLab IR.

Reads, in order of preference:

1. the ``ForgeLab.Document.xml`` sidecar our exporter writes (lossless IR
   round-trip),
2. a legacy ForgeLab-dialect ``Document.xml`` (files exported before the
   real-schema rewrite),
3. genuine FreeCAD ``Document.xml`` (canonical subset: parts, bodies,
   sketches with line/circle geometry and dimensional constraints, pads,
   pockets; Origin planes/axes and other unmodeled objects are skipped).
"""

import xml.etree.ElementTree as ET

from pydantic import ValidationError

from forgelab.formats import FcstdError, read_archive_entry, read_document
from forgelab.importers.base import Importer
from forgelab.importers.mechanical.realxml import parse_real_document
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.spec.mechanical import (
    NODE_BODY,
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
from forgelab.spec.version import SPEC_VERSION

_NODE_BY_FCTYPE = {
    "App::Part": NODE_PART,
    "PartDesign::Body": NODE_BODY,
    "Sketcher::SketchObject": NODE_SKETCH,
    "PartDesign::Pad": NODE_PAD,
    "PartDesign::Pocket": NODE_POCKET,
    "Part::Loft": NODE_LOFT,
    "Part::Sweep": NODE_SWEEP,
    "Part::Fillet": NODE_FILLET,
    "Part::Thickness": NODE_SHELL,
    "Part::Revolution": NODE_REVOLVE,
}

_MODEL_BY_NODE = {
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
}

assert set(_NODE_BY_FCTYPE.values()) == set(_MODEL_BY_NODE), "FreeCAD type maps are out of sync"


class FreeCADParseError(FcstdError):
    """Raised when an FCStd document cannot be mapped to ForgeLab IR."""


class FreeCADImporter(Importer):
    """Import a FreeCAD .FCStd model into ForgeLab IR."""

    tool_name = "freecad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        try:
            sidecar = read_archive_entry(source, "ForgeLab.Document.xml")
        except FcstdError as exc:
            raise FreeCADParseError(str(exc)) from exc
        if sidecar is not None:
            return self._from_dialect(source, member="ForgeLab.Document.xml")

        document_xml = read_archive_entry(source, "Document.xml")
        if document_xml is None:
            raise FreeCADParseError("FCStd archive has no Document.xml")
        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError as exc:
            raise FreeCADParseError(f"Malformed Document.xml: {exc}") from exc
        if root.get("DocName") is not None:
            # Legacy ForgeLab dialect (pre-real-schema exports).
            return self._from_dialect(source, member="Document.xml")
        return self._from_real_schema(root)

    def _from_dialect(self, source: bytes, *, member: str) -> ForgeDocument:
        try:
            fc_doc = read_document(source, member=member)
        except FcstdError as exc:
            raise FreeCADParseError(str(exc)) from exc

        nodes: list[Node] = []
        for obj in fc_doc.objects:
            node_type = _NODE_BY_FCTYPE.get(obj.obj_type)
            if node_type is None:
                raise FreeCADParseError(
                    f"Unknown FreeCAD object type {obj.obj_type!r} on object {obj.name!r}"
                )
            props = {prop.name: prop.value for prop in obj.properties}
            nodes.append(self._node(obj.name, node_type, props))

        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.MECHANICAL,
            meta=DocumentMeta(
                name=fc_doc.name or "freecad-document",
                generator=fc_doc.generator or "forgelab-freecad",
            ),
            nodes=nodes,
        )

    def _from_real_schema(self, root: ET.Element) -> ForgeDocument:
        items = parse_real_document(root)
        if not items:
            raise FreeCADParseError(
                "Document.xml contains no objects ForgeLab can model "
                "(expected parts/bodies/sketches/pads/pockets)"
            )
        nodes = [self._node(name, node_type, props) for name, node_type, props in items]
        label = None
        doc_props = root.find("Properties")
        if doc_props is not None:
            for prop in doc_props.findall("Property"):
                string_el = prop.find("String")
                if prop.get("name") == "Label" and string_el is not None:
                    label = string_el.get("value")
                    break
        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.MECHANICAL,
            meta=DocumentMeta(name=label or "freecad-document", generator="forgelab-freecad"),
            nodes=nodes,
        )

    def _node(self, name: str, node_type: str, props: dict) -> Node:
        model = _MODEL_BY_NODE[node_type]
        try:
            validated = model.model_validate(props)
        except ValidationError as exc:
            raise FreeCADParseError(
                f"Object {name!r} has invalid {node_type} properties: {exc}"
            ) from exc
        return Node(id=name, type=node_type, props=validated.model_dump())
