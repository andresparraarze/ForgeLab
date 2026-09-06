"""STEP and STL exporters for mechanical documents, via the FreeCAD kernel.

``.FCStd`` is FreeCAD's own format. STEP (ISO 10303) is what every other CAD
package reads — SolidWorks, Fusion, Onshape, Inventor — and STL is what slicers
and mesh tools read. Between them they are how a ForgeLab part leaves the
FreeCAD ecosystem at all.

Both are *evaluated* formats: they carry boundary representation or triangles,
not a parametric recipe, so producing them means actually building the part.
That is why these two exporters need FreeCAD when the ``.FCStd`` exporter does
not — the .FCStd writer emits the recipe and lets FreeCAD build it on open,
while a STEP file has to contain the built result.

On ``implemented = True``: the registry-honesty convention (never report a path
as available when it would raise ``NotImplementedError``) is about stubs. These
are not stubs; they are complete implementations with an optional system
dependency, the same shape as the preview extra. Availability is reported
through ``generation_status``'s ``freecad_kernel`` flag, and calling without
FreeCAD raises an error that names what to install.

One asymmetry to know about: ``stl`` is now the only tool name whose importer
and exporter serve different domains. ``StlImporter`` reads a mesh into a
**threed** document; ``StlExporter`` writes one from a **mechanical** part.
``list_formats`` therefore shows ``stl`` as import+export, but the two are not a
round trip. Exporting a threed document as STL fails with a message saying so
rather than producing anything.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from forgelab.exporters.base import Exporter
from forgelab.exporters.mechanical.freecad import FreeCADExporter
from forgelab.formats import freecad_kernel, step
from forgelab.spec import Domain, ForgeDocument


class _KernelExporter(Exporter):
    """Shared machinery: build the .FCStd, then have FreeCAD convert it."""

    #: ``freecad_kernel.convert`` format key.
    fmt: str = ""

    def from_ir(self, document: ForgeDocument) -> bytes:
        if document.domain != Domain.MECHANICAL:
            # Worth being explicit for STL in particular: the STL *importer*
            # reads threed documents, so list_formats shows stl both ways and a
            # caller could reasonably expect a round trip that does not exist.
            raise ValueError(
                f"{self.fmt.upper()} export applies to mechanical documents, not "
                f"{document.domain.value!r}; export a threed document as 'gltf' instead"
            )
        build = FreeCADExporter().build(document)
        if not build.solid_names:
            raise ValueError(
                f"nothing to export to {self.fmt.upper()}: the document defines no "
                f"finished solid (run verify_geometry to find out which feature "
                f"built nothing)"
            )
        with tempfile.TemporaryDirectory(prefix="forgelab-export-") as tmp:
            source = Path(tmp) / "part.FCStd"
            source.write_bytes(build.data)
            target = Path(tmp) / f"part.{self.fmt}"
            freecad_kernel.convert(source, target, self.fmt, names=list(build.solid_names))
            return self._post(target.read_bytes())

    def _post(self, data: bytes) -> bytes:
        return data


class StepExporter(_KernelExporter):
    """Export mechanical IR to STEP (ISO 10303-21) — the CAD interchange format."""

    tool_name = "step"
    fmt = "step"

    def _post(self, data: bytes) -> bytes:
        # OCC stamps the wall clock into the STEP header, so two exports a
        # second apart differ. Pin it, the way the FCStd writer pins its ZIP
        # timestamps, and the same document exports byte-identically every time.
        return step.normalize(data)


class StlExporter(_KernelExporter):
    """Export mechanical IR to binary STL — the mesh format slicers read.

    A tessellation, not a solid: dimensions survive, exact curvature does not.
    Prefer STEP for anything that will be machined or re-modelled.
    """

    tool_name = "stl"
    fmt = "stl"
