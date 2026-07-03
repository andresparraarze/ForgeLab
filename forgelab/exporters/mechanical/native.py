"""Mechanical-CAD native-format exporters (Fusion 360). (stub)"""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class Fusion360Exporter(Exporter):
    """Export ForgeLab IR to a Fusion 360 model. (stub)"""

    implemented = False
    tool_name = "fusion360"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Fusion 360 export is not implemented yet.")
