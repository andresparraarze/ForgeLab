"""Mechanical-CAD importers (Fusion 360, FreeCAD) -> ForgeLab IR. (stubs)"""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class Fusion360Importer(Importer):
    """Import a Fusion 360 model into ForgeLab IR. (stub)"""

    tool_name = "fusion360"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Fusion 360 import is not implemented yet.")


class FreeCADImporter(Importer):
    """Import a FreeCAD model into ForgeLab IR. (stub)"""

    tool_name = "freecad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("FreeCAD import is not implemented yet.")
