"""glTF exporter: ForgeLab IR -> .gltf bytes.

Rebuilds a canonical, self-contained glTF (JSON with one base64-embedded buffer)
from the IR. Materials and meshes are emitted in document order and referenced by
index; the object tree (Node.children) is flattened depth-first into the glTF
node array. Because import assigns ids in that same depth-first order, the
import -> export -> import cycle is an identity over the IR.

Coordinates pass through unchanged: the threed IR is Y-up, the same axis
convention glTF uses natively, so no up-axis conversion is applied on export.
(Authoring Z-up would double-convert through Blender's Y-up->Z-up importer and
land tipped — see ``forgelab.spec.threed``.)
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from forgelab.exporters.base import Exporter
from forgelab.formats.gltf import BufferBuilder
from forgelab.spec import (
    NODE_MATERIAL,
    NODE_MESH,
    NODE_OBJECT,
    NODE_SCENE,
    ForgeDocument,
    Material,
    Mesh,
    Node,
    Object3D,
)
from forgelab.sync.hashing import HASH_KEY, document_hash


def _resolve_ref(ref: str, index: dict[str, int], kind: str) -> int:
    """Map a node-id reference to its glTF array index, or fail clearly.

    A reference that doesn't match a node id (a common mistake is using the
    target's display ``name`` instead of its ``id``) raises a ``ValueError`` that
    names the bad reference and lists the valid ids, instead of a cryptic KeyError.
    """
    try:
        return index[ref]
    except KeyError:
        available = ", ".join(index) or "(none)"
        raise ValueError(
            f"{kind} reference {ref!r} does not match any {kind} node id. "
            f"References must use the target node's id field, not its display "
            f"name. Available {kind} ids: {available}."
        ) from None


# Sampler constants from the glTF 2.0 schema. LINEAR magnification with
# trilinear mipmapping and REPEAT wrapping is the ordinary choice for a
# surface-detail texture, and REPEAT is the spec default for wrapS/wrapT.
_LINEAR = 9729
_LINEAR_MIPMAP_LINEAR = 9987
_REPEAT = 10497


def _embed_image(path: str, base_dir: Path | None) -> dict[str, Any]:
    """Read a texture file and return a glTF ``images`` entry embedding it.

    The image goes in as a base64 data URI, matching how geometry already
    travels in this exporter's single embedded buffer — a ``.gltf`` ForgeLab
    writes stays one self-contained file with no sibling assets to lose. The
    glTF schema allows exactly one of ``uri`` / ``bufferView`` per image, and a
    data URI carries its own media type, so no separate ``mimeType`` is needed
    (that field is only required alongside ``bufferView``).
    """
    resolved = Path(path)
    if not resolved.is_absolute() and base_dir is not None:
        resolved = base_dir / resolved
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise ValueError(
            f"base_color_texture {path!r} could not be read ({exc.strerror}). "
            f"Texture paths resolve relative to the document's directory"
            + (f" ({base_dir})" if base_dir is not None else ", which is unknown here")
            + "."
        ) from None
    mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    uri = f"data:{mime};base64," + base64.b64encode(data).decode()
    return {"name": Path(path).name, "uri": uri}


class GltfExporter(Exporter):
    """Convert a ForgeDocument into glTF bytes.

    ``base_dir`` is the document's directory, used to resolve a material's
    ``base_color_texture`` path (mirroring the importers' ``base_dir``). A
    document with no textures does not need it.
    """

    tool_name = "gltf"

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else None

    def from_ir(self, document: ForgeDocument) -> bytes:
        material_nodes = [n for n in document.nodes if n.type == NODE_MATERIAL]
        mesh_nodes = [n for n in document.nodes if n.type == NODE_MESH]
        scene_nodes = [n for n in document.nodes if n.type == NODE_SCENE]
        # Root objects live at the document top level (canonical importer
        # output), but agents also nest them under the scene node — accept both.
        root_objects = [n for n in document.nodes if n.type == NODE_OBJECT]
        root_objects += [
            c for scene in scene_nodes for c in scene.children if c.type == NODE_OBJECT
        ]

        mat_index = {n.id: i for i, n in enumerate(material_nodes)}
        mesh_index = {n.id: i for i, n in enumerate(mesh_nodes)}

        gltf: dict[str, Any] = {
            "asset": {
                "version": "2.0",
                "generator": "forgelab-gltf",
                "extras": {HASH_KEY: document_hash(document.model_dump(mode="json"))},
            }
        }

        materials = []
        images: list[dict[str, Any]] = []
        textures: list[dict[str, Any]] = []
        texture_of_path: dict[str, int] = {}
        for n in material_nodes:
            m = Material.model_validate(n.props)
            pbr: dict[str, Any] = {
                "baseColorFactor": m.base_color,
                "metallicFactor": m.metallic,
                "roughnessFactor": m.roughness,
            }
            if m.base_color_texture:
                # Several materials may share one image file; emit it once.
                if m.base_color_texture not in texture_of_path:
                    images.append(_embed_image(m.base_color_texture, self.base_dir))
                    textures.append({"sampler": 0, "source": len(images) - 1})
                    texture_of_path[m.base_color_texture] = len(textures) - 1
                # textureInfo: texCoord defaults to 0 (TEXCOORD_0), so it is
                # left out. baseColorFactor stays: the spec defines it as a
                # linear multiplier over the sampled texels, not an
                # alternative to them.
                pbr["baseColorTexture"] = {"index": texture_of_path[m.base_color_texture]}
            mat_entry: dict[str, Any] = {"name": m.name, "pbrMetallicRoughness": pbr}
            # glTF materials default to alphaMode OPAQUE, under which viewers
            # ignore baseColorFactor's alpha entirely — a translucent material
            # must say BLEND explicitly or it renders solid.
            if m.base_color[3] < 1.0:
                mat_entry["alphaMode"] = "BLEND"
            materials.append(mat_entry)
        if materials:
            gltf["materials"] = materials
        if images:
            gltf["images"] = images
            gltf["samplers"] = [
                {
                    "magFilter": _LINEAR,
                    "minFilter": _LINEAR_MIPMAP_LINEAR,
                    "wrapS": _REPEAT,
                    "wrapT": _REPEAT,
                }
            ]
            gltf["textures"] = textures

        builder = BufferBuilder()
        meshes = []
        for n in mesh_nodes:
            mesh = Mesh.model_validate(n.props)
            prims = []
            for prim in mesh.primitives:
                attributes = {"POSITION": builder.add_vec3(prim.positions)}
                if prim.uvs:
                    attributes["TEXCOORD_0"] = builder.add_vec2(prim.uvs)
                entry: dict[str, Any] = {"attributes": attributes}
                if prim.indices:
                    entry["indices"] = builder.add_scalar_uint(prim.indices)
                if prim.material:
                    entry["material"] = _resolve_ref(prim.material, mat_index, "material")
                prims.append(entry)
            meshes.append({"name": mesh.name, "primitives": prims})
        if meshes:
            gltf["meshes"] = meshes

        gltf_nodes: list[dict[str, Any]] = []

        def add_object(node: Node) -> int:
            obj = Object3D.model_validate(node.props)
            entry: dict[str, Any] = {
                "name": obj.name,
                "translation": obj.transform.translation,
                "rotation": obj.transform.rotation,
                "scale": obj.transform.scale,
            }
            if obj.mesh:
                entry["mesh"] = _resolve_ref(obj.mesh, mesh_index, "mesh")
            my_index = len(gltf_nodes)
            gltf_nodes.append(entry)
            child_indices = [add_object(c) for c in node.children if c.type == NODE_OBJECT]
            if child_indices:
                gltf_nodes[my_index]["children"] = child_indices
            return my_index

        root_indices = [add_object(n) for n in root_objects]
        if gltf_nodes:
            gltf["nodes"] = gltf_nodes

        if builder.accessors:
            gltf["accessors"] = builder.accessors
            gltf["bufferViews"] = builder.buffer_views
            gltf["buffers"] = [builder.buffer()]

        scene_name = scene_nodes[0].props.get("name", "scene") if scene_nodes else "scene"
        gltf["scenes"] = [{"name": scene_name, "nodes": root_indices}]
        gltf["scene"] = 0

        return (json.dumps(gltf, indent=2) + "\n").encode()
