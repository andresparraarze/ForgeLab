"""Triangles for a mechanical part, tessellated by the real OCC kernel.

A threed document *contains* its triangles, so previewing one is a matter of
reading the IR. A mechanical document contains none: it is a parametric recipe —
sketch, pad, pocket, revolve — and the surface only exists once OpenCASCADE has
evaluated it. There is no honest way to draw a filleted, shelled, boolean-cut
part without asking the kernel, so this module exports the document and has
FreeCAD tessellate the solids it built.

That makes the mechanical preview require FreeCAD, unlike the threed one. The
alternative — approximating pads and pockets in pure Python — would draw
confident pictures of exactly the features most likely to be wrong, which is
worse than drawing nothing.

Coordinates come back in FreeCAD's native **Z-up millimetres**, which is already
matplotlib's convention, so no axis remap is applied. (The threed path does
remap, from glTF's Y-up. Applying that here would lay every part on its side.)

Depends on ``forgelab.spec`` plus the mechanical exporter and the kernel bridge
— the same shape as ``forgelab.verify``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from forgelab.exporters.mechanical.freecad import FreeCADExporter
from forgelab.formats import freecad_kernel
from forgelab.spec import ForgeDocument

_Triangle = list[tuple[float, float, float]]
_Rgba = tuple[float, float, float, float]

# One hue per solid, so a multi-body part reads as separate pieces instead of a
# single grey blob. Muted and desaturated: this is a diagnostic image, and
# saturated colour would compete with the shading that conveys the form.
_SOLID_COLORS: tuple[_Rgba, ...] = (
    (0.62, 0.66, 0.72, 1.0),  # steel
    (0.76, 0.66, 0.50, 1.0),  # brass
    (0.58, 0.70, 0.62, 1.0),  # patina
    (0.72, 0.60, 0.62, 1.0),  # copper
    (0.66, 0.64, 0.76, 1.0),  # violet-grey
)


def collect_triangles(
    document: ForgeDocument, deviation: float = freecad_kernel.DEFAULT_DEVIATION
) -> tuple[list[_Triangle], list[_Rgba]]:
    """World-space triangles + per-triangle colors for a mechanical document.

    Exports the document, has FreeCAD recompute and tessellate its finished
    solids, and flattens the result into the ``(triangles, colors)`` pair the
    renderer takes. ``deviation`` is the tessellation tolerance in mm — smaller
    means smoother curves and more facets.

    Only the *finished* solids are tessellated. A body renders its tip's shape,
    so drawing both would paint the raw pad over the fillet built from it; the
    exporter reports which objects are final and that selection is used here.

    Returns two empty lists when the feature tree built nothing — a real
    outcome, not an error, and the caller says so in its own terms.
    """
    build = FreeCADExporter().build(document)
    with tempfile.TemporaryDirectory(prefix="forgelab-preview-") as tmp:
        target = Path(tmp) / f"{document.meta.name or 'part'}.FCStd"
        target.write_bytes(build.data)
        meshes = freecad_kernel.tessellate(
            target, names=list(build.solid_names), deviation=deviation
        )

    triangles: list[_Triangle] = []
    colors: list[_Rgba] = []
    for index, mesh in enumerate(meshes):
        vertices = mesh["vertices"]
        color = _SOLID_COLORS[index % len(_SOLID_COLORS)]
        for facet in mesh["facets"]:
            a, b, c = facet[0], facet[1], facet[2]
            triangles.append(
                [
                    (vertices[a][0], vertices[a][1], vertices[a][2]),
                    (vertices[b][0], vertices[b][1], vertices[b][2]),
                    (vertices[c][0], vertices[c][1], vertices[c][2]),
                ]
            )
            colors.append(color)
    return triangles, colors
