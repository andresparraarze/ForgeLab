"""Blender Python (bpy) script exporter: ForgeLab threed IR -> a runnable .py.

Instead of glTF triangle soup, this compiles a threed document into a Blender
script that rebuilds the scene with native objects, Principled BSDF materials,
and recognised primitives (cube / cylinder / UV sphere) where the geometry
matches, falling back to raw ``from_pydata`` meshes otherwise. The script clears
the default scene, sets the scene name, and adds a camera plus three-point
lighting so the result renders immediately.

Run it inside Blender 4.0+ (Text Editor -> Run Script) or via a Blender MCP
``execute_blender_code`` call.

Axis convention: the threed IR is Y-up (glTF's convention); Blender is Z-up. The
whole scene is parented to a single root empty rotated +90 deg about X, the same
Y-up -> Z-up conversion Blender's glTF importer applies, so a document authored
Y-up lands upright.
"""

from __future__ import annotations

import math
from typing import Any

from forgelab.exporters.base import Exporter
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

_TOL = 1e-4


def _f(value: float) -> str:
    return repr(float(value))


def _vec(seq: Any) -> str:
    return "(" + ", ".join(_f(v) for v in seq) + ")"


def _points(positions: list[float]) -> list[tuple[float, float, float]]:
    return [(positions[i], positions[i + 1], positions[i + 2]) for i in range(0, len(positions), 3)]


def _unique(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    seen: dict[tuple[float, float, float], None] = {}
    for p in points:
        seen.setdefault((round(p[0], 5), round(p[1], 5), round(p[2], 5)), None)
    return list(seen)


def _detect_box(points: list[tuple[float, float, float]]) -> dict[str, Any] | None:
    uniq = _unique(points)
    if len(uniq) != 8:
        return None
    xs = sorted({p[0] for p in uniq})
    ys = sorted({p[1] for p in uniq})
    zs = sorted({p[2] for p in uniq})
    if not (len(xs) == 2 and len(ys) == 2 and len(zs) == 2):
        return None
    corners = {(x, y, z) for x in xs for y in ys for z in zs}
    if set(uniq) != corners:
        return None
    center = ((xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2, (zs[0] + zs[1]) / 2)
    half = ((xs[1] - xs[0]) / 2, (ys[1] - ys[0]) / 2, (zs[1] - zs[0]) / 2)
    if min(half) <= _TOL:
        return None
    return {"kind": "cube", "center": center, "half": half}


def _detect_cylinder(points: list[tuple[float, float, float]]) -> dict[str, Any] | None:
    uniq = _unique(points)
    n = len(uniq)
    if n < 8 or (n - 2) % 2 != 0:
        return None
    cx = sum(p[0] for p in uniq) / n
    cy = sum(p[1] for p in uniq) / n
    cz = sum(p[2] for p in uniq) / n
    center = (cx, cy, cz)
    for axis in (0, 1, 2):
        o1, o2 = [i for i in (0, 1, 2) if i != axis]
        radii = [math.hypot(p[o1] - center[o1], p[o2] - center[o2]) for p in uniq]
        along = sorted({round(p[axis], 5) for p in uniq})
        if len(along) != 2:
            continue
        caps = [r for r in radii if r <= _TOL]
        ring = [r for r in radii if r > _TOL]
        if len(caps) != 2 or not ring:
            continue
        rmax, rmin = max(ring), min(ring)
        if rmax - rmin > _TOL or rmax <= _TOL:
            continue
        return {
            "kind": "cylinder",
            "center": center,
            "radius": rmax,
            "depth": along[1] - along[0],
            "axis": axis,
            "segments": len(ring) // 2,
        }
    return None


def _detect_sphere(points: list[tuple[float, float, float]]) -> dict[str, Any] | None:
    uniq = _unique(points)
    if len(uniq) < 12:
        return None
    cx = sum(p[0] for p in uniq) / len(uniq)
    cy = sum(p[1] for p in uniq) / len(uniq)
    cz = sum(p[2] for p in uniq) / len(uniq)
    radii = [math.dist(p, (cx, cy, cz)) for p in uniq]
    if max(radii) - min(radii) > _TOL or min(radii) <= _TOL:
        return None
    return {"kind": "sphere", "center": (cx, cy, cz), "radius": sum(radii) / len(radii)}


def _detect_primitive(mesh: Mesh) -> dict[str, Any] | None:
    """Recognise a cube / cylinder / sphere in a single-primitive mesh, else None."""
    if len(mesh.primitives) != 1:
        return None
    points = _points(mesh.primitives[0].positions)
    if len(points) < 8:
        return None
    return _detect_box(points) or _detect_cylinder(points) or _detect_sphere(points)


def _geo_matrix_expr(desc: dict[str, Any]) -> str:
    """A mathutils.Matrix expression placing a unit primitive at the detected pose."""
    c = desc["center"]
    if desc["kind"] == "cube":
        h = desc["half"]
        return (
            f"Matrix.Translation({_vec(c)}) @ "
            f"Matrix.Diagonal(({_f(h[0])}, {_f(h[1])}, {_f(h[2])}, 1.0))"
        )
    if desc["kind"] == "cylinder":
        r, half = desc["radius"], desc["depth"] / 2.0
        rot = {
            0: "Matrix.Rotation(math.radians(90.0), 4, 'Y')",
            1: "Matrix.Rotation(math.radians(-90.0), 4, 'X')",
            2: "Matrix.Identity(4)",
        }[desc["axis"]]
        return (
            f"Matrix.Translation({_vec(c)}) @ {rot} @ "
            f"Matrix.Diagonal(({_f(r)}, {_f(r)}, {_f(half)}, 1.0))"
        )
    # sphere
    r = desc["radius"]
    return f"Matrix.Translation({_vec(c)}) @ Matrix.Diagonal(({_f(r)}, {_f(r)}, {_f(r)}, 1.0))"


def _bounds(meshes: dict[str, Mesh]) -> tuple[tuple[float, float, float], float]:
    """Bounding-box centre and radius over all mesh geometry (IR/Y-up space)."""
    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]
    for mesh in meshes.values():
        for prim in mesh.primitives:
            for p in _points(prim.positions):
                for k in range(3):
                    lo[k] = min(lo[k], p[k])
                    hi[k] = max(hi[k], p[k])
    if lo[0] == math.inf:
        return (0.0, 0.0, 0.0), 5.0
    center = tuple((lo[k] + hi[k]) / 2 for k in range(3))
    radius = max(math.dist(lo, hi) / 2, 1.0)
    return center, radius  # type: ignore[return-value]


class BlenderScriptExporter(Exporter):
    """Compile a ForgeLab threed document into a runnable Blender bpy script."""

    tool_name = "blender_script"

    def from_ir(self, document: ForgeDocument) -> bytes:
        material_nodes = [n for n in document.nodes if n.type == NODE_MATERIAL]
        mesh_nodes = [n for n in document.nodes if n.type == NODE_MESH]
        scene_nodes = [n for n in document.nodes if n.type == NODE_SCENE]
        root_objects = [n for n in document.nodes if n.type == NODE_OBJECT]
        root_objects += [
            c for scene in scene_nodes for c in scene.children if c.type == NODE_OBJECT
        ]

        materials = {n.id: Material.model_validate(n.props) for n in material_nodes}
        meshes = {n.id: Mesh.model_validate(n.props) for n in mesh_nodes}

        scene_name = scene_nodes[0].props.get("name", "Scene") if scene_nodes else "Scene"

        lines: list[str] = []
        lines += self._header(scene_name)
        lines += self._materials_block(materials)
        lines.append("")
        lines.append("objects = []")
        n_objects = 0
        for node in root_objects:
            n_objects += self._object_block(node, meshes, lines, parent="root")
        lines.append("")
        lines += self._camera_and_lights(*_bounds(meshes))
        lines.append("")
        lines.append("bpy.context.view_layer.update()")
        lines.append(
            f'print("ForgeLab: built scene {scene_name!r} with "'
            f' "{n_objects} object(s), {len(materials)} material(s), '
            f'a camera and three-point lighting")'
        )
        return ("\n".join(lines) + "\n").encode("utf-8")

    # -- script sections ---------------------------------------------------- #
    def _header(self, scene_name: str) -> list[str]:
        return [
            "# Generated by ForgeLab (tool='blender_script'). Run in Blender 4.0+.",
            "import bpy",
            "import math",
            "from mathutils import Matrix, Quaternion",
            "",
            "",
            "def _trs(t, r, s):",
            "    # IR transform: translation, rotation quaternion [x, y, z, w], scale.",
            "    return (Matrix.Translation(t)",
            "            @ Quaternion((r[3], r[0], r[1], r[2])).to_matrix().to_4x4()",
            "            @ Matrix.Diagonal((s[0], s[1], s[2], 1.0)))",
            "",
            "",
            "def _parent(obj, parent, local):",
            "    obj.parent = parent",
            "    obj.matrix_parent_inverse = Matrix.Identity(4)",
            "    obj.matrix_basis = local",
            "",
            "",
            "# --- clear the default scene ---",
            "bpy.ops.object.select_all(action='SELECT')",
            "bpy.ops.object.delete(use_global=False)",
            "for _block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras,",
            "               bpy.data.lights):",
            "    for _d in list(_block):",
            "        if _d.users == 0:",
            "            _block.remove(_d)",
            "",
            "scene = bpy.context.scene",
            f"scene.name = {scene_name!r}",
            "",
            "# --- Y-up -> Z-up conversion root (matches Blender's glTF importer) ---",
            'root = bpy.data.objects.new("ForgeLab_Root", None)',
            "scene.collection.objects.link(root)",
            "root.rotation_euler = (math.radians(90.0), 0.0, 0.0)",
        ]

    def _materials_block(self, materials: dict[str, Material]) -> list[str]:
        lines = ["", "# --- materials (Principled BSDF) ---", "materials = {}"]
        for mid, mat in materials.items():
            col = mat.base_color
            rgba = (col + [1.0, 1.0, 1.0, 1.0])[:4]
            lines += [
                f"m = bpy.data.materials.new({mat.name!r})",
                "m.use_nodes = True",
                'bsdf = m.node_tree.nodes.get("Principled BSDF")',
                f'bsdf.inputs["Base Color"].default_value = {_vec(rgba)}',
                f'bsdf.inputs["Metallic"].default_value = {_f(mat.metallic)}',
                f'bsdf.inputs["Roughness"].default_value = {_f(mat.roughness)}',
                f"materials[{mid!r}] = m",
            ]
        return lines

    def _object_block(
        self, node: Node, meshes: dict[str, Mesh], lines: list[str], parent: str
    ) -> int:
        obj = Object3D.model_validate(node.props)
        var = f"obj_{len(lines)}"
        mesh = meshes.get(obj.mesh) if obj.mesh else None
        geo_expr = "Matrix.Identity(4)"

        lines.append("")
        lines.append(f"# object {node.id}")
        if mesh is not None:
            desc = _detect_primitive(mesh)
            if desc is not None:
                lines += self._primitive_add(desc)
                geo_expr = _geo_matrix_expr(desc)
                lines.append(f"{var} = bpy.context.active_object")
                lines.append(f"{var}.name = {obj.name!r}")
                self._append_materials(var, mesh, lines, slots_only_first=True)
            else:
                lines += self._raw_mesh(var, obj.name, mesh)
        else:
            lines.append("bpy.ops.object.empty_add()")
            lines.append(f"{var} = bpy.context.active_object")
            lines.append(f"{var}.name = {obj.name!r}")

        t = obj.transform
        lines.append(
            f"_parent({var}, {parent}, _trs({_vec(t.translation)}, "
            f"{_vec(t.rotation)}, {_vec(t.scale)}) @ {geo_expr})"
        )
        lines.append(f"objects.append({var})")
        count = 1
        for child in node.children:
            if child.type == NODE_OBJECT:
                count += self._object_block(child, meshes, lines, parent=var)
        return count

    def _primitive_add(self, desc: dict[str, Any]) -> list[str]:
        if desc["kind"] == "cube":
            return ["bpy.ops.mesh.primitive_cube_add(size=2.0)"]
        if desc["kind"] == "cylinder":
            return [
                f"bpy.ops.mesh.primitive_cylinder_add(vertices={desc['segments']}, "
                "radius=1.0, depth=2.0)"
            ]
        return ["bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0)"]

    def _raw_mesh(self, var: str, name: str, mesh: Mesh) -> list[str]:
        verts: list[tuple[float, float, float]] = []
        faces: list[tuple[int, int, int]] = []
        face_mat: list[int] = []
        slots: list[str] = []
        slot_index: dict[str, int] = {}
        for prim in mesh.primitives:
            base = len(verts)
            verts += _points(prim.positions)
            if prim.material and prim.material not in slot_index:
                slot_index[prim.material] = len(slots)
                slots.append(prim.material)
            mi = slot_index.get(prim.material, 0)
            idx = prim.indices or list(range(len(prim.positions) // 3))
            for i in range(0, len(idx) - 2, 3):
                faces.append((base + idx[i], base + idx[i + 1], base + idx[i + 2]))
                face_mat.append(mi)
        vert_str = "[" + ", ".join(_vec(v) for v in verts) + "]"
        face_str = "[" + ", ".join("(" + ", ".join(map(str, f)) + ")" for f in faces) + "]"
        lines = [
            f"mesh = bpy.data.meshes.new({name!r})",
            f"mesh.from_pydata({vert_str}, [], {face_str})",
            "mesh.update()",
            f"{var} = bpy.data.objects.new({name!r}, mesh)",
            f"scene.collection.objects.link({var})",
        ]
        for mid in slots:
            lines.append(f"{var}.data.materials.append(materials[{mid!r}])")
        if slots and any(m != 0 for m in face_mat):
            mats_str = "[" + ", ".join(map(str, face_mat)) + "]"
            lines.append(f"for _poly, _mi in zip(mesh.polygons, {mats_str}):")
            lines.append("    _poly.material_index = _mi")
        return lines

    def _append_materials(
        self, var: str, mesh: Mesh, lines: list[str], slots_only_first: bool
    ) -> None:
        mat = mesh.primitives[0].material if mesh.primitives else ""
        if mat:
            lines.append(f"{var}.data.materials.append(materials[{mat!r}])")

    def _camera_and_lights(self, center: tuple[float, float, float], radius: float) -> list[str]:
        cx, cy, cz = center
        r = radius

        def loc(dx: float, dy: float, dz: float) -> str:
            return _vec((cx + dx * r, cy + dy * r, cz + dz * r))

        return [
            "# --- camera + three-point lighting (framed on the scene bounds) ---",
            'target = bpy.data.objects.new("ForgeLab_Target", None)',
            "scene.collection.objects.link(target)",
            f"_parent(target, root, Matrix.Translation({_vec(center)}))",
            "",
            'cam_data = bpy.data.cameras.new("ForgeLab_Camera")',
            'cam = bpy.data.objects.new("ForgeLab_Camera", cam_data)',
            "scene.collection.objects.link(cam)",
            f"_parent(cam, root, Matrix.Translation({loc(1.7, 1.2, 2.6)}))",
            "_cam_track = cam.constraints.new('TRACK_TO')",
            "_cam_track.target = target",
            "scene.camera = cam",
            "",
            "def _add_light(name, kind, energy, size, location):",
            "    ld = bpy.data.lights.new(name, kind)",
            "    ld.energy = energy",
            "    if kind == 'AREA':",
            "        ld.size = size",
            "    o = bpy.data.objects.new(name, ld)",
            "    scene.collection.objects.link(o)",
            "    _parent(o, root, Matrix.Translation(location))",
            "    c = o.constraints.new('TRACK_TO')",
            "    c.target = target",
            "    return o",
            "",
            f'_add_light("Key", "AREA", {_f(1200.0 * r)}, {_f(r)}, {loc(2.2, 2.4, 1.8)})',
            f'_add_light("Fill", "AREA", {_f(400.0 * r)}, {_f(1.5 * r)}, {loc(-2.6, 1.2, 1.4)})',
            f'_add_light("Rim", "AREA", {_f(700.0 * r)}, {_f(r)}, {loc(0.0, 1.8, -3.0)})',
        ]
