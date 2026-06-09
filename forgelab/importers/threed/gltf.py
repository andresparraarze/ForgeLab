"""glTF importer: .gltf bytes -> ForgeLab IR.

Decodes a self-contained glTF (JSON with a base64-embedded buffer) into the
generic Node graph. Materials and meshes become flat top-level nodes; scene
objects form a tree via ``Node.children``. Geometry is fully decoded into plain
float/int arrays so agents work with real numbers, not opaque buffers.

Object ids are assigned in scene depth-first order (name when present, else
``object_<n>``), which keeps import -> export -> import stable regardless of the
original glTF node-array order.
"""

from __future__ import annotations

import json
from typing import Any

from forgelab.formats.gltf import GltfError, decode_accessor
from forgelab.importers.base import Importer
from forgelab.spec import (
    NODE_MATERIAL,
    NODE_MESH,
    NODE_OBJECT,
    NODE_SCENE,
    DocumentMeta,
    Domain,
    ForgeDocument,
    Material,
    Mesh,
    Node,
    Object3D,
    Primitive,
    Transform,
)
from forgelab.spec.version import SPEC_VERSION


class GltfParseError(GltfError):
    """Raised when glTF bytes cannot be imported."""


def _material_id(gltf: dict, index: int) -> str:
    materials = gltf.get("materials", [])
    name = materials[index].get("name") if 0 <= index < len(materials) else None
    return name or f"material_{index}"


def _mesh_id(gltf: dict, index: int) -> str:
    meshes = gltf.get("meshes", [])
    name = meshes[index].get("name") if 0 <= index < len(meshes) else None
    return name or f"mesh_{index}"


class GltfImporter(Importer):
    """Convert glTF bytes into a ForgeDocument."""

    tool_name = "gltf"

    def to_ir(self, source: bytes) -> ForgeDocument:
        try:
            gltf = json.loads(source)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GltfParseError(f"not valid JSON: {exc}") from exc
        if not isinstance(gltf, dict):
            raise GltfParseError("glTF root must be a JSON object")
        version = gltf.get("asset", {}).get("version")
        if version != "2.0":
            raise GltfParseError(f"unsupported glTF asset version {version!r}")

        nodes: list[Node] = []

        scene_index = gltf.get("scene", 0)
        scenes = gltf.get("scenes", [])
        scene = scenes[scene_index] if 0 <= scene_index < len(scenes) else {}
        scene_name = scene.get("name") or "scene"
        nodes.append(Node(id=scene_name, type=NODE_SCENE, props={"name": scene_name}))

        for i, mat in enumerate(gltf.get("materials", [])):
            model = self._material(mat)
            nodes.append(
                Node(id=_material_id(gltf, i), type=NODE_MATERIAL, props=model.model_dump())
            )

        for i, mesh in enumerate(gltf.get("meshes", [])):
            model = self._mesh(gltf, mesh)
            nodes.append(Node(id=_mesh_id(gltf, i), type=NODE_MESH, props=model.model_dump()))

        counter = [0]
        for root in scene.get("nodes", []):
            nodes.append(self._object(gltf, root, counter))

        meta = DocumentMeta(name=scene_name, generator="forgelab-gltf")
        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.THREED,
            meta=meta,
            nodes=nodes,
        )

    def _material(self, mat: dict) -> Material:
        pbr = mat.get("pbrMetallicRoughness", {})
        return Material(
            name=mat.get("name") or "material",
            base_color=list(pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])),
            metallic=pbr.get("metallicFactor", 1.0),
            roughness=pbr.get("roughnessFactor", 1.0),
        )

    def _mesh(self, gltf: dict, mesh: dict) -> Mesh:
        prims: list[Primitive] = []
        for prim in mesh.get("primitives", []):
            pos_index = prim.get("attributes", {}).get("POSITION")
            if pos_index is None:
                raise GltfParseError("primitive missing POSITION attribute")
            positions = [float(v) for v in decode_accessor(gltf, pos_index)]
            indices: list[int] = []
            if "indices" in prim:
                indices = [int(v) for v in decode_accessor(gltf, prim["indices"])]
            material = ""
            if "material" in prim:
                material = _material_id(gltf, prim["material"])
            prims.append(Primitive(positions=positions, indices=indices, material=material))
        return Mesh(name=mesh.get("name") or "mesh", primitives=prims)

    def _object(self, gltf: dict, index: int, counter: list[int]) -> Node:
        gltf_nodes = gltf.get("nodes", [])
        gnode = gltf_nodes[index]
        name = gnode.get("name")
        node_id = name or f"object_{counter[0]}"
        counter[0] += 1

        transform = Transform(
            translation=[float(v) for v in gnode.get("translation", [0.0, 0.0, 0.0])],
            rotation=[float(v) for v in gnode.get("rotation", [0.0, 0.0, 0.0, 1.0])],
            scale=[float(v) for v in gnode.get("scale", [1.0, 1.0, 1.0])],
        )
        mesh_ref = _mesh_id(gltf, gnode["mesh"]) if "mesh" in gnode else ""
        obj = Object3D(name=name or node_id, transform=transform, mesh=mesh_ref)

        children = [self._object(gltf, c, counter) for c in gnode.get("children", [])]
        props: dict[str, Any] = obj.model_dump()
        return Node(id=node_id, type=NODE_OBJECT, props=props, children=children)
