"""Mechanical-CAD exporters (Fusion 360, FreeCAD) from ForgeLab IR. (stubs)"""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class Fusion360Exporter(Exporter):
    """Export ForgeLab IR to a Fusion 360 model. (stub)"""

    tool_name = "fusion360"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Fusion 360 export is not implemented yet.")


class FreeCADExporter(Exporter):
    """Export ForgeLab IR to a FreeCAD model. (stub)"""

    tool_name = "freecad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("FreeCAD export is not implemented yet.")
