"""glTF exporter: ForgeLab IR -> .gltf bytes.

Rebuilds a canonical, self-contained glTF (JSON with one base64-embedded buffer)
from the IR. Materials and meshes are emitted in document order and referenced by
index; the object tree (Node.children) is flattened depth-first into the glTF
node array. Because import assigns ids in that same depth-first order, the
import -> export -> import cycle is an identity over the IR.
"""

from __future__ import annotations

import json
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


class GltfExporter(Exporter):
    """Convert a ForgeDocument into glTF bytes."""

    tool_name = "gltf"

    def from_ir(self, document: ForgeDocument) -> bytes:
        material_nodes = [n for n in document.nodes if n.type == NODE_MATERIAL]
        mesh_nodes = [n for n in document.nodes if n.type == NODE_MESH]
        scene_nodes = [n for n in document.nodes if n.type == NODE_SCENE]
        root_objects = [n for n in document.nodes if n.type == NODE_OBJECT]

        mat_index = {n.id: i for i, n in enumerate(material_nodes)}
        mesh_index = {n.id: i for i, n in enumerate(mesh_nodes)}

        gltf: dict[str, Any] = {"asset": {"version": "2.0", "generator": "forgelab-gltf"}}

        materials = []
        for n in material_nodes:
            m = Material.model_validate(n.props)
            materials.append(
                {
                    "name": m.name,
                    "pbrMetallicRoughness": {
                        "baseColorFactor": m.base_color,
                        "metallicFactor": m.metallic,
                        "roughnessFactor": m.roughness,
                    },
                }
            )
        if materials:
            gltf["materials"] = materials

        builder = BufferBuilder()
        meshes = []
        for n in mesh_nodes:
            mesh = Mesh.model_validate(n.props)
            prims = []
            for prim in mesh.primitives:
                entry: dict[str, Any] = {
                    "attributes": {"POSITION": builder.add_vec3(prim.positions)},
                }
                if prim.indices:
                    entry["indices"] = builder.add_scalar_uint(prim.indices)
                if prim.material:
                    entry["material"] = mat_index[prim.material]
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
                entry["mesh"] = mesh_index[obj.mesh]
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
