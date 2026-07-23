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
from pathlib import Path
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
from forgelab.spec.threed import Modifier

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


def _mean(values: list[float]) -> float:
    """The arithmetic mean, identical on every interpreter and platform.

    ``math.fsum`` rather than the builtin ``sum``: CPython 3.12 changed
    ``sum()`` over floats to Neumaier compensated summation (gh-100425), so the
    same coordinates averaged to ``0.0`` on 3.12+ and ``6.27e-17`` on 3.11.
    Those centres are written straight into the generated script, which made the
    export bytes a function of the interpreter version. ``fsum`` is correctly
    rounded by definition, so it has no such freedom.
    """
    return math.fsum(values) / len(values)


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
    center = (
        _mean([p[0] for p in uniq]),
        _mean([p[1] for p in uniq]),
        _mean([p[2] for p in uniq]),
    )
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
    center = (
        _mean([p[0] for p in uniq]),
        _mean([p[1] for p in uniq]),
        _mean([p[2] for p in uniq]),
    )
    radii = [math.dist(p, center) for p in uniq]
    if max(radii) - min(radii) > _TOL or min(radii) <= _TOL:
        return None
    return {"kind": "sphere", "center": center, "radius": _mean(radii)}


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


Vec3 = tuple[float, float, float]


def _bounds(meshes: dict[str, Mesh]) -> tuple[Vec3, float, Vec3, Vec3]:
    """Bounds over all mesh geometry (IR/Y-up): (centre, radius, lo, hi)."""
    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]
    for mesh in meshes.values():
        for prim in mesh.primitives:
            for p in _points(prim.positions):
                for k in range(3):
                    lo[k] = min(lo[k], p[k])
                    hi[k] = max(hi[k], p[k])
    if lo[0] == math.inf:
        return (0.0, 0.0, 0.0), 5.0, (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)
    center = tuple((lo[k] + hi[k]) / 2 for k in range(3))
    radius = max(math.dist(lo, hi) / 2, 1.0)
    return center, radius, tuple(lo), tuple(hi)  # type: ignore[return-value]


def _camera_location(center: Vec3, radius: float) -> Vec3:
    """Camera position for a 3/4 product shot: 45 deg azimuth, 30 deg elevation.

    Computed in the IR's Y-up space (the camera is parented to the conversion
    root): azimuth sweeps the X/Z ground plane, elevation lifts along +Y. The
    distance is scaled to the bounding sphere so an 85mm lens frames the subject.
    """
    azim = math.radians(45.0)
    elev = math.radians(30.0)
    dist = max(radius * 4.5, 1.0)
    dx = dist * math.cos(elev) * math.sin(azim)
    dy = dist * math.sin(elev)
    dz = dist * math.cos(elev) * math.cos(azim)
    return (center[0] + dx, center[1] + dy, center[2] + dz)


def _sort_for_boolean_targets(roots: list[Node]) -> list[Node]:
    """Order root object subtrees so every boolean modifier target exists first.

    A boolean modifier references its target by node id, and the generated
    script assigns ``_mod.object`` to the bpy object variable created earlier —
    so the target's subtree must be emitted before the subtree that cuts with
    it. Raises ``ValueError`` naming the objects when the dependencies form a
    cycle.
    """
    owner: dict[str, int] = {}

    def collect(node: Node, idx: int) -> None:
        owner[node.id] = idx
        for child in node.children:
            if child.type == NODE_OBJECT:
                collect(child, idx)

    for i, root in enumerate(roots):
        collect(root, i)

    deps: dict[int, set[int]] = {i: set() for i in range(len(roots))}

    def add_edges(node: Node, idx: int) -> None:
        for mod in node.props.get("modifiers") or []:
            if isinstance(mod, dict) and mod.get("type") == "boolean":
                target_idx = owner.get(str(mod.get("target", "")))
                if target_idx is not None and target_idx != idx:
                    deps[idx].add(target_idx)
        for child in node.children:
            if child.type == NODE_OBJECT:
                add_edges(child, idx)

    for i, root in enumerate(roots):
        add_edges(root, i)

    ordered: list[int] = []
    done: set[int] = set()
    visiting: set[int] = set()

    def visit(i: int, path: list[int]) -> None:
        if i in done:
            return
        if i in visiting:
            cycle = path[path.index(i) :] + [i]
            names = " -> ".join(roots[j].id for j in cycle)
            raise ValueError(f"boolean modifier dependency cycle between objects: {names}")
        visiting.add(i)
        for dep in sorted(deps[i]):
            visit(dep, [*path, i])
        visiting.discard(i)
        done.add(i)
        ordered.append(i)

    for i in range(len(roots)):
        visit(i, [])
    return [roots[i] for i in ordered]


class BlenderScriptExporter(Exporter):
    """Compile a ForgeLab threed document into a runnable Blender bpy script.

    ``base_dir`` is the document's directory, used to turn a material's
    relative ``base_color_texture`` into the absolute path the generated script
    hands to ``bpy.data.images.load`` (mirroring the importers' ``base_dir``).
    A document with no textures does not need it.
    """

    tool_name = "blender_script"

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else None

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
        center, radius, lo, _hi = _bounds(meshes)

        lines: list[str] = []
        lines += self._header(scene_name)
        lines += self._render_settings()
        lines += self._world_sky()
        lines += self._materials_block(materials)
        lines.append("")
        lines.append("objects = []")
        n_objects = 0
        var_of: dict[str, str] = {}
        for node in _sort_for_boolean_targets(root_objects):
            n_objects += self._object_block(node, meshes, lines, parent="root", var_of=var_of)
        lines.append("")
        lines += self._ground_plane(center, radius, lo)
        lines.append("")
        lines += self._camera_and_lights(center, radius)
        lines.append("")
        lines.append("bpy.context.view_layer.update()")
        lines.append(
            f'print("ForgeLab: built scene {scene_name!r} with "'
            f' "{n_objects} object(s), {len(materials)} material(s), a daylight-sky world, "'
            f' "a ground plane, an 85mm product-shot camera and three-point lighting")'
        )
        lines.append("")
        lines += self._render_output()
        return ("\n".join(lines) + "\n").encode("utf-8")

    # -- script sections ---------------------------------------------------- #
    def _header(self, scene_name: str) -> list[str]:
        return [
            "# Generated by ForgeLab (tool='blender_script'). Run in Blender 4.0+.",
            "import bpy",
            "import math",
            "from mathutils import Matrix, Quaternion",
            "",
            "# Flip to False for a high-quality CYCLES render; True is a fast EEVEE preview.",
            "PREVIEW = True",
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
            ]
            if mat.base_color_texture:
                lines += self._image_texture_nodes(mat, rgba)
            lines.append(f"materials[{mid!r}] = m")
        return lines

    def _image_texture_nodes(self, mat: Material, rgba: list[float]) -> list[str]:
        """Wire an Image Texture node into the Principled BSDF's Base Color.

        The node graph mirrors what Blender's own glTF importer builds for a
        ``baseColorTexture`` (``glTF-Blender-IO``'s ``pbrMetallicRoughness.py``),
        so a ForgeLab script and an imported ``.gltf`` of the same document
        produce the same material:

        - A white ``base_color`` links the texture's Color straight to Base
          Color — no extra node, which is also the graph anyone hand-building
          this would expect.
        - Any other colour goes through a ``ShaderNodeMix`` in ``RGBA`` /
          ``MULTIPLY`` mode, because glTF defines ``baseColorFactor`` as a
          multiplier over the sampled texels, not a replacement. Its colour
          sockets are addressed **by index** (6 and 7, result 2): the RGBA Mix
          node has several sockets sharing the names "A"/"B"/"Result", so
          lookup by name picks the wrong (float) ones. That indexing is copied
          from Blender's importer, not guessed.
        """
        path = self._texture_path(mat.base_color_texture)
        lines = [
            f"_img = bpy.data.images.load({path!r}, check_existing=True)",
            '_tex = m.node_tree.nodes.new("ShaderNodeTexImage")',
            "_tex.image = _img",
            f"_tex.label = {mat.base_color_texture!r}",
        ]
        if rgba[:3] == [1.0, 1.0, 1.0]:
            lines.append(
                '_ = m.node_tree.links.new(bsdf.inputs["Base Color"], _tex.outputs["Color"])'
            )
        else:
            lines += [
                '_mix = m.node_tree.nodes.new("ShaderNodeMix")',
                '_mix.data_type = "RGBA"',
                '_mix.blend_type = "MULTIPLY"',
                '_mix.inputs["Factor"].default_value = 1.0',
                f"_mix.inputs[7].default_value = {_vec([*rgba[:3], 1.0])}",
                "_ = m.node_tree.links.new(_mix.inputs[6], _tex.outputs['Color'])",
                '_ = m.node_tree.links.new(bsdf.inputs["Base Color"], _mix.outputs[2])',
            ]
        return lines

    def _texture_path(self, texture: str) -> str:
        """Absolute path to a texture, so the script runs from any directory."""
        path = Path(texture)
        if not path.is_absolute() and self.base_dir is not None:
            path = self.base_dir / path
        return str(path)

    def _object_block(
        self,
        node: Node,
        meshes: dict[str, Mesh],
        lines: list[str],
        parent: str,
        var_of: dict[str, str],
    ) -> int:
        obj = Object3D.model_validate(node.props)
        var = f"obj_{len(lines)}"
        var_of[node.id] = var
        mesh = meshes.get(obj.mesh) if obj.mesh else None
        geo_expr = "Matrix.Identity(4)"

        lines.append("")
        lines.append(f"# object {node.id}")
        if mesh is not None:
            # Explicit uvs are an authored unwrap, so the geometry must be built
            # verbatim: swapping in bpy.ops.mesh.primitive_cube_add would
            # silently substitute Blender's own default UV layout for it.
            desc = None if any(p.uvs for p in mesh.primitives) else _detect_primitive(mesh)
            if desc is not None:
                lines += self._primitive_add(desc)
                geo_expr = _geo_matrix_expr(desc)
                lines.append(f"{var} = bpy.context.active_object")
                lines.append(f"{var}.name = {obj.name!r}")
                self._append_materials(var, mesh, lines, slots_only_first=True)
            else:
                lines += self._raw_mesh(var, obj.name, mesh)
        else:
            if obj.modifiers:
                raise ValueError(
                    f"object {node.id!r} has modifiers but no mesh; "
                    "modifiers need mesh geometry to act on"
                )
            lines.append("bpy.ops.object.empty_add()")
            lines.append(f"{var} = bpy.context.active_object")
            lines.append(f"{var}.name = {obj.name!r}")

        t = obj.transform
        lines.append(
            f"_parent({var}, {parent}, _trs({_vec(t.translation)}, "
            f"{_vec(t.rotation)}, {_vec(t.scale)}) @ {geo_expr})"
        )
        lines.append(f"objects.append({var})")
        for mod in obj.modifiers:
            lines += self._modifier_lines(node.id, var, mod, var_of)
        count = 1
        for child in node.children:
            if child.type == NODE_OBJECT:
                count += self._object_block(child, meshes, lines, parent=var, var_of=var_of)
        return count

    def _modifier_lines(
        self, node_id: str, var: str, mod: Modifier, var_of: dict[str, str]
    ) -> list[str]:
        """Native bpy modifier-stack calls for one modifier, in stack order."""
        if mod.type == "subsurf":
            render_levels = mod.render_levels if mod.render_levels is not None else mod.levels
            return [
                f"_mod = {var}.modifiers.new('Subsurf', 'SUBSURF')",
                f"_mod.levels = {int(mod.levels)}",
                f"_mod.render_levels = {int(render_levels)}",
            ]
        if mod.type == "bevel":
            return [
                f"_mod = {var}.modifiers.new('Bevel', 'BEVEL')",
                f"_mod.width = {_f(mod.width)}",
                f"_mod.segments = {int(mod.segments)}",
                f"_mod.limit_method = {mod.limit_method.upper()!r}",
            ]
        if mod.type == "boolean":
            target_var = var_of.get(mod.target)
            if target_var is None:
                raise ValueError(
                    f"object {node_id!r}: boolean modifier target {mod.target!r} "
                    "is not an object node created earlier in the script"
                )
            return [
                f"_mod = {var}.modifiers.new('Boolean', 'BOOLEAN')",
                f"_mod.operation = {mod.operation.upper()!r}",
                f"_mod.object = {target_var}",
                "# the boolean consumes its target visually, so hide it",
                f"{target_var}.hide_render = True",
                f"{target_var}.hide_set(True)",
            ]
        # solidify
        return [
            f"_mod = {var}.modifiers.new('Solidify', 'SOLIDIFY')",
            f"_mod.thickness = {_f(mod.thickness)}",
        ]

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
        uvs: list[tuple[float, float]] = []
        has_uvs = any(prim.uvs for prim in mesh.primitives)
        for prim in mesh.primitives:
            base = len(verts)
            verts += _points(prim.positions)
            if has_uvs:
                # A primitive without uvs in a mesh that has them still needs a
                # pair per vertex to keep the layer parallel to the vertices.
                pairs = list(zip(prim.uvs[0::2], prim.uvs[1::2], strict=True))
                uvs += pairs or [(0.0, 0.0)] * (len(prim.positions) // 3)
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
        ]
        if has_uvs:
            # from_pydata creates no UV layer, so one is added and filled per
            # face corner (loop), which is where Blender stores UVs.
            #
            # V IS FLIPPED. glTF puts the UV origin at the top-left, Blender at
            # the bottom-left; Blender's own glTF importer converts with
            # "u,v -> u,1-v" (uvs_gltf_to_blender in glTF-Blender-IO). The IR
            # follows glTF, so the same flip belongs here — without it every
            # texture lands mirrored vertically against the .gltf export.
            uv_str = "[" + ", ".join(f"({_f(u)}, {_f(1.0 - v)})" for u, v in uvs) + "]"
            lines += [
                f"_uvs = {uv_str}",
                '_uv_layer = mesh.uv_layers.new(name="UVMap")',
                "for _loop in mesh.loops:",
                "    _uv_layer.data[_loop.index].uv = _uvs[_loop.vertex_index]",
            ]
        lines += [
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

    def _camera_and_lights(self, center: Vec3, radius: float) -> list[str]:
        cx, cy, cz = center
        r = radius
        cam_loc = _camera_location(center, radius)

        def loc(dx: float, dy: float, dz: float) -> str:
            return _vec((cx + dx * r, cy + dy * r, cz + dz * r))

        return [
            "# --- camera: 3/4 product angle (azimuth 45deg, elevation 30deg), 85mm lens ---",
            'target = bpy.data.objects.new("ForgeLab_Target", None)',
            "scene.collection.objects.link(target)",
            f"_parent(target, root, Matrix.Translation({_vec(center)}))",
            "",
            'cam_data = bpy.data.cameras.new("ForgeLab_Camera")',
            "cam_data.lens = 85.0  # flattering product-shot focal length",
            'cam = bpy.data.objects.new("ForgeLab_Camera", cam_data)',
            "scene.collection.objects.link(cam)",
            f"_parent(cam, root, Matrix.Translation({_vec(cam_loc)}))",
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

    def _render_settings(self) -> list[str]:
        return [
            "",
            "# --- render settings: CYCLES 128-sample quality, EEVEE 64-sample preview ---",
            "scene.render.resolution_x = 1920",
            "scene.render.resolution_y = 1080",
            "scene.render.resolution_percentage = 100",
            "if PREVIEW:",
            "    try:",
            "        scene.render.engine = 'BLENDER_EEVEE_NEXT'  # Blender 4.2+",
            "    except TypeError:",
            "        scene.render.engine = 'BLENDER_EEVEE'  # Blender 4.0/4.1",
            "    try:",
            "        scene.eevee.taa_render_samples = 64",
            "    except AttributeError:",
            "        pass",
            "else:",
            "    scene.render.engine = 'CYCLES'",
            "    scene.cycles.samples = 128",
            "# Denoising on. Prefer OpenImageDenoise (Blender 3.5+, CPU & GPU);",
            "# fall back to NLM only on older builds that lack it.",
            "scene.cycles.use_denoising = True",
            "try:",
            "    scene.cycles.denoiser = 'OPENIMAGEDENOISE'",
            "except (TypeError, AttributeError):",
            "    try:",
            "        scene.cycles.denoiser = 'NLM'",
            "    except (TypeError, AttributeError):",
            "        pass",
        ]

    def _world_sky(self) -> list[str]:
        # We can't embed a real HDRI, so stand in with a procedural daylight sky
        # wired through a Background node (the Environment-Texture slot's role).
        return [
            "",
            "# --- world: procedural daylight sky (HDRI stand-in), strength 1.0 ---",
            "world = bpy.data.worlds.new('ForgeLab_World')",
            "scene.world = world",
            "world.use_nodes = True",
            "_wnodes = world.node_tree.nodes",
            "_wlinks = world.node_tree.links",
            "_wnodes.clear()",
            "_w_out = _wnodes.new('ShaderNodeOutputWorld')",
            "_w_bg = _wnodes.new('ShaderNodeBackground')",
            "_w_bg.inputs['Strength'].default_value = 1.0",
            "_w_sky = _wnodes.new('ShaderNodeTexSky')",
            "# Sky type: prefer HOSEK_WILKIE (closest to Nishita's realistic daylight,",
            "# and Nishita was removed in Blender 5.x); fall back to PREETHAM, else skip.",
            "try:",
            "    _w_sky.sky_type = 'HOSEK_WILKIE'",
            "except (TypeError, AttributeError):",
            "    try:",
            "        _w_sky.sky_type = 'PREETHAM'",
            "    except (TypeError, AttributeError):",
            "        pass",
            "# Sun angle props are Nishita-era; guard them for non-Nishita sky types.",
            "try:",
            "    _w_sky.sun_elevation = math.radians(45.0)",
            "    _w_sky.sun_rotation = math.radians(30.0)",
            "except (TypeError, AttributeError):",
            "    pass",
            "_wlinks.new(_w_sky.outputs['Color'], _w_bg.inputs['Color'])",
            "_wlinks.new(_w_bg.outputs['Background'], _w_out.inputs['Surface'])",
        ]

    def _ground_plane(self, center: Vec3, radius: float, lo: Vec3) -> list[str]:
        # World space (Z-up): IR (x, y, z) maps to Blender (x, -z, y) under the
        # conversion root, so the lowest Blender Z is the minimum IR Y.
        offset = max(radius * 0.01, 0.001)
        ground_loc = (center[0], -center[2], lo[1] - offset)
        size = max(radius * 20.0, 10.0)
        return [
            "# --- ground plane (shadow catcher / context), light grey, roughness 0.8 ---",
            "_ground_mat = bpy.data.materials.new('ForgeLab_Ground')",
            "_ground_mat.use_nodes = True",
            "_gbsdf = _ground_mat.node_tree.nodes.get('Principled BSDF')",
            "_gbsdf.inputs['Base Color'].default_value = (0.9, 0.9, 0.9, 1.0)",
            "_gbsdf.inputs['Roughness'].default_value = 0.8",
            f"bpy.ops.mesh.primitive_plane_add(size={_f(size)}, location={_vec(ground_loc)})",
            "ground = bpy.context.active_object",
            "ground.name = 'ForgeLab_Ground'",
            "ground.data.materials.append(_ground_mat)",
        ]

    def _render_output(self) -> list[str]:
        return [
            "# --- render to <script>_render.png next to this script ---",
            "try:",
            "    _script_path = __file__",
            "except NameError:",
            "    _script_path = bpy.data.filepath or 'forgelab_scene.py'",
            "scene.render.filepath = _script_path.replace('.py', '_render.png')",
            "bpy.ops.render.render(write_still=True)",
        ]
