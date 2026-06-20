"""Wavefront OBJ importer: .obj (+ companion .mtl) bytes -> ForgeLab IR.

Parses OBJ geometry into the threed Node graph: each ``o``/``g`` named object or
group becomes its own mesh + object node pair, faces are fan-triangulated, and
``usemtl`` runs split a group's geometry into per-material primitives. When the
file's directory is known (``base_dir``), the ``mtllib`` ``.mtl`` is parsed for
PBR material values; anything referenced but undefined falls back to a default
grey material. Standard library only.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

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

_DEFAULT_MATERIAL_ID = "default_material"


class ObjParseError(ValueError):
    """Raised when OBJ bytes cannot be imported."""


def _default_material() -> Material:
    return Material(name="default", base_color=[0.6, 0.6, 0.6, 1.0], metallic=0.0, roughness=0.5)


def _material_from(acc: dict) -> Material:
    """Build a Material from an accumulating .mtl record (Kd/Ns/Pm/d)."""
    kd = acc["kd"]
    ns = acc.get("ns")
    # Specular exponent 0..1000 -> roughness (shiny = low roughness).
    roughness = max(0.0, min(1.0, 1.0 - ns / 1000.0)) if ns is not None else 0.5
    metallic = max(0.0, min(1.0, acc.get("pm", 0.0)))
    return Material(
        name=acc["name"],
        base_color=[kd[0], kd[1], kd[2], acc["alpha"]],
        metallic=metallic,
        roughness=roughness,
    )


def _identity() -> Transform:
    return Transform(
        translation=[0.0, 0.0, 0.0], rotation=[0.0, 0.0, 0.0, 1.0], scale=[1.0, 1.0, 1.0]
    )


def _parse_index(token: str, n_verts: int) -> int:
    """Resolve an OBJ face vertex reference (``v``, ``v/vt``, ``v/vt/vn``) to 0-based."""
    raw = token.split("/", 1)[0]
    i = int(raw)
    return n_verts + i if i < 0 else i - 1


class ObjImporter(Importer):
    """Convert Wavefront OBJ bytes into a ForgeDocument."""

    tool_name = "obj"

    def __init__(self, base_dir: str | Path | None = None, source_name: str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else None
        self.source_name = source_name

    def to_ir(self, source: bytes) -> ForgeDocument:
        text = source.decode("utf-8", errors="replace")
        verts: list[tuple[float, float, float]] = []
        groups: list[dict] = []
        current: dict | None = None
        current_mat = ""
        mtl_libs: list[str] = []

        def new_group(name: str) -> dict:
            group = {"name": name, "faces": []}
            groups.append(group)
            return group

        for line in text.splitlines():
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            tag = parts[0]
            if tag == "v":
                try:
                    verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except (IndexError, ValueError) as exc:
                    raise ObjParseError(f"bad vertex line: {line!r}") from exc
            elif tag in ("o", "g"):
                current = new_group(" ".join(parts[1:]) or f"object_{len(groups)}")
            elif tag == "mtllib":
                mtl_libs.extend(parts[1:])
            elif tag == "usemtl":
                current_mat = " ".join(parts[1:])
            elif tag == "f":
                if current is None:
                    current = new_group("object")
                try:
                    idxs = [_parse_index(t, len(verts)) for t in parts[1:]]
                except ValueError as exc:
                    raise ObjParseError(f"bad face line: {line!r}") from exc
                if len(idxs) >= 3:
                    current["faces"].append((current_mat, idxs))

        mtl_defs = self._load_materials(mtl_libs)
        return self._build(verts, groups, mtl_defs)

    def _load_materials(self, libs: list[str]) -> dict[str, Material]:
        """Parse companion .mtl files (when ``base_dir`` is set) into Material models."""
        defs: dict[str, Material] = {}
        if not self.base_dir:
            return defs
        for lib in libs:
            path = self.base_dir / lib
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            current: dict = {}
            for line in text.splitlines():
                parts = line.split()
                if not parts or parts[0].startswith("#"):
                    continue
                tag = parts[0]
                if tag == "newmtl":
                    current = {"name": " ".join(parts[1:]), "kd": [0.6, 0.6, 0.6], "alpha": 1.0}
                elif not current:
                    continue
                elif tag == "Kd" and len(parts) >= 4:
                    current["kd"] = [float(parts[1]), float(parts[2]), float(parts[3])]
                elif tag == "Ns" and len(parts) >= 2:
                    current["ns"] = float(parts[1])
                elif tag == "Pm" and len(parts) >= 2:
                    current["pm"] = float(parts[1])
                elif tag in ("d", "Tr") and len(parts) >= 2:
                    val = float(parts[1])
                    current["alpha"] = val if tag == "d" else 1.0 - val
                if current:
                    defs[current["name"]] = _material_from(current)
        return defs

    def _build(
        self,
        verts: list[tuple[float, float, float]],
        groups: list[dict],
        mtl_defs: dict[str, Material],
    ) -> ForgeDocument:
        scene_name = self.source_name or "scene"
        nodes: list[Node] = [Node(id=scene_name, type=NODE_SCENE, props={"name": scene_name})]

        materials: OrderedDict[str, Material] = OrderedDict()

        def material_id(name: str) -> str:
            if name and name in mtl_defs:
                materials.setdefault(name, mtl_defs[name])
                return name
            materials.setdefault(_DEFAULT_MATERIAL_ID, _default_material())
            return _DEFAULT_MATERIAL_ID

        mesh_nodes: list[Node] = []
        object_nodes: list[Node] = []
        used_ids: set[str] = {scene_name}

        for index, group in enumerate(groups):
            if not group["faces"]:
                continue
            by_mat: OrderedDict[str, list[tuple[int, int, int]]] = OrderedDict()
            for mat, idxs in group["faces"]:
                tris = [(idxs[0], idxs[i], idxs[i + 1]) for i in range(1, len(idxs) - 1)]
                by_mat.setdefault(mat, []).extend(tris)

            prims: list[Primitive] = []
            for mat, tris in by_mat.items():
                positions, indices = self._local_geometry(verts, tris)
                if not positions:
                    continue
                prims.append(
                    Primitive(positions=positions, indices=indices, material=material_id(mat))
                )
            if not prims:
                continue

            base = group["name"] or f"object_{index}"
            obj_id = _unique(base, used_ids)
            mesh_id = _unique(f"{base}_mesh", used_ids)
            mesh_nodes.append(
                Node(
                    id=mesh_id, type=NODE_MESH, props=Mesh(name=base, primitives=prims).model_dump()
                )
            )
            obj = Object3D(name=base, transform=_identity(), mesh=mesh_id)
            object_nodes.append(Node(id=obj_id, type=NODE_OBJECT, props=obj.model_dump()))

        for mat_id, mat in materials.items():
            nodes.append(Node(id=mat_id, type=NODE_MATERIAL, props=mat.model_dump()))
        nodes.extend(mesh_nodes)
        nodes.extend(object_nodes)

        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.THREED,
            meta=DocumentMeta(name=scene_name, generator="forgelab-obj"),
            nodes=nodes,
        )

    def _local_geometry(
        self, verts: list[tuple[float, float, float]], tris: list[tuple[int, int, int]]
    ) -> tuple[list[float], list[int]]:
        remap: dict[int, int] = {}
        positions: list[float] = []
        indices: list[int] = []
        for tri in tris:
            for gi in tri:
                if not 0 <= gi < len(verts):
                    raise ObjParseError(f"face references vertex {gi + 1} out of range")
                if gi not in remap:
                    remap[gi] = len(positions) // 3
                    positions.extend(verts[gi])
                indices.append(remap[gi])
        return positions, indices


def _unique(candidate: str, used: set[str]) -> str:
    name = candidate
    n = 1
    while name in used:
        name = f"{candidate}_{n}"
        n += 1
    used.add(name)
    return name
