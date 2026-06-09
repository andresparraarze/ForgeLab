"""FreeCAD .FCStd importer -> ForgeLab IR."""

from pydantic import ValidationError

from forgelab.formats import FcstdError, read_document
from forgelab.importers.base import Importer
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
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
from forgelab.spec.version import SPEC_VERSION

_NODE_BY_FCTYPE = {
    "App::Part": NODE_PART,
    "PartDesign::Body": NODE_BODY,
    "Sketcher::SketchObject": NODE_SKETCH,
    "PartDesign::Pad": NODE_PAD,
    "PartDesign::Pocket": NODE_POCKET,
}

_MODEL_BY_NODE = {
    NODE_PART: Part,
    NODE_BODY: Body,
    NODE_SKETCH: Sketch,
    NODE_PAD: Pad,
    NODE_POCKET: Pocket,
}

assert set(_NODE_BY_FCTYPE.values()) == set(_MODEL_BY_NODE), "FreeCAD type maps are out of sync"


class FreeCADParseError(FcstdError):
    """Raised when an FCStd document cannot be mapped to ForgeLab IR."""


class FreeCADImporter(Importer):
    """Import a FreeCAD .FCStd model into ForgeLab IR."""

    tool_name = "freecad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        try:
            fc_doc = read_document(source)
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
            model = _MODEL_BY_NODE[node_type]
            try:
                validated = model.model_validate(props)
            except ValidationError as exc:
                raise FreeCADParseError(
                    f"Object {obj.name!r} has invalid {node_type} properties: {exc}"
                ) from exc
            nodes.append(Node(id=obj.name, type=node_type, props=validated.model_dump()))

        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.MECHANICAL,
            meta=DocumentMeta(
                name=fc_doc.name or "freecad-document",
                generator=fc_doc.generator or "forgelab-freecad",
            ),
            nodes=nodes,
        )
