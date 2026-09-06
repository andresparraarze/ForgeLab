"""Flat-shaded multi-angle preview renders of ForgeLab documents.

Renders a document's triangles with matplotlib's ``Poly3DCollection`` — no
Blender, no GPU, no system dependencies, just the ``preview`` extra (matplotlib
+ numpy). The technique matches the proven manual workflow: get the geometry
into matplotlib's Z-up axes, shade each face by a fixed light direction, and lay
several camera angles side by side in one PNG so a single image shows the whole
shape.

Two domains, two ways of getting the triangles:

- **threed** documents already carry baked triangle meshes, so the geometry
  comes straight from the IR (:func:`collect_triangles`). The renderer draws
  the base meshes: Blender modifier stacks (subsurf/bevel/boolean/solidify) are
  procedural descriptions evaluated by Blender itself.
- **mechanical** documents carry a parametric feature tree with no triangles in
  it at all, so :mod:`forgelab.preview.mechanical` has the real OCC kernel
  tessellate the built solids. That needs FreeCAD installed.

Depends only on ``forgelab.spec`` (boundary rule); matplotlib and numpy are
imported lazily so the core library works without the extra installed.
"""

from __future__ import annotations

import math
from typing import Any

from forgelab.spec import Domain, ForgeDocument, Node
from forgelab.spec.threed import NODE_MATERIAL, NODE_MESH, NODE_OBJECT

# (name, elevation, azimuth) camera presets, in the order views are taken.
_VIEWS = (
    ("front-3/4", 22.0, -60.0),
    ("side", 12.0, 0.0),
    ("rear-3/4", 22.0, 120.0),
    ("top", 75.0, -90.0),
)

# Mechanical parts are read as engineering drawings, not as scenes: one pictorial
# view to show the form, then the orthographic elevations a machinist expects.
# Straight-on angles are deliberate — they are what makes a hole look round and a
# wall look parallel, which is how a proportion error becomes visible at all.
_MECHANICAL_VIEWS = (
    ("iso", 30.0, -60.0),
    ("front", 0.0, -90.0),
    ("right", 0.0, 0.0),
    ("top", 90.0, -90.0),
)

_LIGHT_DIR = (0.35, 0.45, 0.82)  # fixed key light, roughly over the shoulder
_DEFAULT_COLOR = (0.62, 0.64, 0.68, 1.0)


class PreviewError(ValueError):
    """Raised when a document cannot be preview-rendered (no geometry...)."""


def _quat_matrix(q: list[float]) -> list[list[float]]:
    x, y, z, w = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def _compose(parent: list[list[float]], local: list[list[float]]) -> list[list[float]]:
    """Compose two 3x4 affine transforms (rotation*scale | translation).

    The dot products go through ``math.fsum`` rather than the builtin ``sum``:
    CPython 3.12 switched ``sum()`` over floats to Neumaier compensated
    summation (gh-100425), so a naive left-to-right ``sum`` of the same three
    products can round one ULP apart on 3.11 versus 3.12+. These matrix cells
    place preview vertices, which would make the rendered pixels depend on the
    interpreter version -- the same defect that once made the Blender exporter's
    bytes version-dependent. ``fsum`` is correctly rounded by definition, so it
    has no such freedom.
    """
    out = [[0.0] * 4 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            out[i][j] = math.fsum(parent[i][k] * local[k][j] for k in range(3))
        out[i][3] = math.fsum([parent[i][3], *(parent[i][k] * local[k][3] for k in range(3))])
    return out


def _affine(props: dict[str, Any]) -> list[list[float]]:
    transform = props.get("transform") or {}
    t = transform.get("translation") or [0.0, 0.0, 0.0]
    r = transform.get("rotation") or [0.0, 0.0, 0.0, 1.0]
    s = transform.get("scale") or [1.0, 1.0, 1.0]
    rot = _quat_matrix([float(v) for v in r])
    return [[rot[i][j] * float(s[j]) for j in range(3)] + [float(t[i])] for i in range(3)]


_IDENTITY = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]


def collect_triangles(
    document: ForgeDocument,
) -> tuple[list[list[tuple[float, float, float]]], list[tuple[float, float, float, float]]]:
    """World-space triangles + per-triangle base colors from the object graph.

    Walks the ``Node.children`` hierarchy composing each object's transform
    onto its parent's, applies the result to the referenced mesh's positions,
    and resolves each primitive's material to its RGBA base color. Coordinates
    stay in the document's Y-up convention (the renderer remaps for display).
    """
    meshes = {n.id: n.props for n in document.walk() if n.type == NODE_MESH}
    materials = {n.id: n.props for n in document.walk() if n.type == NODE_MATERIAL}

    triangles: list[list[tuple[float, float, float]]] = []
    colors: list[tuple[float, float, float, float]] = []

    def color_of(material_ref: str) -> tuple[float, float, float, float]:
        props = materials.get(material_ref)
        base = (props or {}).get("base_color")
        if isinstance(base, list) and len(base) == 4:
            return (float(base[0]), float(base[1]), float(base[2]), float(base[3]))
        return _DEFAULT_COLOR

    def visit(node: Node, parent: list[list[float]]) -> None:
        world = parent
        if node.type == NODE_OBJECT:
            world = _compose(parent, _affine(node.props))
            mesh = meshes.get(str(node.props.get("mesh", "")))
            if mesh:
                for prim in mesh.get("primitives") or []:
                    pos = prim.get("positions") or []
                    idx = prim.get("indices") or []
                    color = color_of(str(prim.get("material", "")))
                    for k in range(0, len(idx) - 2, 3):
                        tri = []
                        for vi in (idx[k], idx[k + 1], idx[k + 2]):
                            x, y, z = pos[3 * vi], pos[3 * vi + 1], pos[3 * vi + 2]
                            tri.append(
                                (
                                    world[0][0] * x
                                    + world[0][1] * y
                                    + world[0][2] * z
                                    + world[0][3],
                                    world[1][0] * x
                                    + world[1][1] * y
                                    + world[1][2] * z
                                    + world[1][3],
                                    world[2][0] * x
                                    + world[2][1] * y
                                    + world[2][2] * z
                                    + world[2][3],
                                )
                            )
                        triangles.append(tri)
                        colors.append(color)
        for child in node.children:
            visit(child, world)

    for node in document.nodes:
        visit(node, _IDENTITY)
    return triangles, colors


def render_preview(document: ForgeDocument, output_path: str, views: int = 3) -> dict[str, Any]:
    """Render a flat-shaded multi-angle preview PNG of a document.

    Handles both threed (baked meshes from the IR) and mechanical (the FreeCAD
    kernel tessellates the built solids) documents.

    Returns ``{"triangle_count", "views"}`` (``views`` is the list of view
    names rendered). Raises ``PreviewError`` for an unsupported domain or a
    document with no geometry, ``ImportError`` when the ``preview`` extra is not
    installed, and — for mechanical — ``FreeCADKernelError`` without FreeCAD.
    """
    if document.domain == Domain.MECHANICAL:
        from forgelab.preview import mechanical

        triangles, colors = mechanical.collect_triangles(document)
        if not triangles:
            raise PreviewError(
                "part has no solid geometry to render — the feature tree built "
                "nothing (run geometry verification to find out which feature)"
            )
        return _render_triangles(triangles, colors, output_path, views, _MECHANICAL_VIEWS)

    if document.domain != Domain.THREED:
        raise PreviewError(
            f"preview rendering applies to threed and mechanical documents, "
            f"not {document.domain.value!r}"
        )
    triangles, colors = collect_triangles(document)
    if not triangles:
        raise PreviewError(
            "scene has no triangle geometry to render — add mesh nodes with "
            "positions/indices and object nodes referencing them"
        )
    # Y-up (glTF convention) -> matplotlib Z-up, right-handed: (x, y, z) -> (x, -z, y).
    # Mechanical geometry arrives from FreeCAD already Z-up and is NOT remapped;
    # doing so would lay every part on its side.
    remapped = [[(x, -z, y) for x, y, z in tri] for tri in triangles]
    return _render_triangles(remapped, colors, output_path, views, _VIEWS)


def _render_triangles(
    triangles: list[list[tuple[float, float, float]]],
    colors: list[tuple[float, float, float, float]],
    output_path: str,
    views: int,
    view_presets: tuple[tuple[str, float, float], ...],
) -> dict[str, Any]:
    """Rasterise world-space Z-up triangles into a multi-view PNG.

    Domain-agnostic on purpose: everything domain-specific (where triangles come
    from, which way is up, which camera angles read well) is settled by the
    caller, so both domains share one shading and layout path.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    tris = np.array(triangles, dtype=float)

    # Flat shading: face normal against the fixed light, floored so back faces
    # stay visible instead of going black.
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.where(lengths == 0, 1.0, lengths)
    light = np.array(_LIGHT_DIR) / np.linalg.norm(_LIGHT_DIR)
    shade = 0.35 + 0.65 * np.clip(np.abs(normals @ light), 0.0, 1.0)
    base = np.array(colors, dtype=float)
    face_colors = np.column_stack([base[:, :3] * shade[:, None], base[:, 3]])

    # Frame each axis on its own extent and give the drawing box those same
    # proportions. Every axis then maps one millimetre to the same distance on
    # screen — so nothing is distorted — while the shape fills the canvas.
    #
    # The earlier approach put the largest extent on all three axes, which is
    # also undistorted but wastes the frame on anything that is not roughly
    # cubic: a 100x60x3 plate got a 115mm-tall Z axis and rendered as a sliver
    # in a mostly empty image. Flat parts are the mechanical common case.
    lo, hi = tris.reshape(-1, 3).min(axis=0), tris.reshape(-1, 3).max(axis=0)
    centre = (lo + hi) / 2
    extent = hi - lo
    # A perfectly flat part has a zero extent on one axis; keep the box finite.
    span = np.maximum(extent, float(extent.max()) * 1e-3 or 1.0) * 1.05

    view_list = view_presets[: max(1, min(views, len(view_presets)))]
    fig = plt.figure(figsize=(4.4 * len(view_list), 4.4), dpi=110)
    for i, (name, elev, azim) in enumerate(view_list, start=1):
        ax = fig.add_subplot(1, len(view_list), i, projection="3d")
        collection = Poly3DCollection(tris, facecolors=face_colors, edgecolors="none")
        ax.add_collection3d(collection)
        for setter, c in ((ax.set_xlim, 0), (ax.set_ylim, 1), (ax.set_zlim, 2)):
            setter(centre[c] - span[c] / 2, centre[c] + span[c] / 2)
        ax.set_box_aspect(tuple(span))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        ax.set_title(name, fontsize=10)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"triangle_count": len(triangles), "views": [name for name, _, _ in view_list]}
