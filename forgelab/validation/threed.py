"""Constraint sanity checks for threed-domain documents.

These run after structural (Pydantic) validation, catching scene mistakes that
would otherwise surface as a crash in an exporter or — worse — as a silently
wrong render. Like the other domain checks they return human-readable
``errors`` (fatal) and ``warnings`` (non-fatal), and return two empty lists for
documents of any other domain so callers can run them unconditionally.

Pure standard library; node payloads are read as plain dicts.
"""

from __future__ import annotations

from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.threed import NODE_MATERIAL, NODE_MESH


def check_threed(document: ForgeDocument) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a threed document."""
    if document.domain != Domain.THREED:
        return [], []

    nodes = list(document.walk())
    errors: list[str] = []
    warnings: list[str] = []

    material_nodes = {n.id: n for n in nodes if n.type == NODE_MATERIAL}
    textured = {
        nid: str(n.props.get("base_color_texture", ""))
        for nid, n in material_nodes.items()
        if n.props.get("base_color_texture")
    }

    for node in nodes:
        if node.type != NODE_MESH:
            continue
        for i, prim in enumerate(node.props.get("primitives") or []):
            if not isinstance(prim, dict):
                continue
            material = str(prim.get("material", ""))
            if not material:
                continue
            if material not in material_nodes:
                # The exporters raise on this too, but reporting it here means
                # validate_document names it instead of the export blowing up.
                available = ", ".join(sorted(material_nodes)) or "(none)"
                errors.append(
                    f"mesh {node.id!r} primitive {i} references material {material!r} "
                    f"which is not a material node id in the document "
                    f"(available: {available})"
                )
                continue
            # A texture needs somewhere to land. Without uvs the image cannot be
            # mapped at all: glTF has no TEXCOORD_0 to point baseColorTexture at,
            # and Blender's Image Texture node falls back to generated
            # coordinates — a wrong render rather than an error.
            if material in textured and not prim.get("uvs"):
                errors.append(
                    f"material {material!r} has a texture "
                    f"({textured[material]!r}) but mesh {node.id!r} primitive {i} "
                    f"has no UV coordinates to map it onto; add 'uvs' "
                    f"(one [u, v] pair per position) to that primitive"
                )

    # UVs with no texture anywhere are harmless — they just carry an unwrap the
    # document is not using yet — so that direction is not even a warning.
    return errors, warnings
