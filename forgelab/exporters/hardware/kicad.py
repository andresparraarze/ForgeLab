"""KiCad exporter (stub — implemented in a later task)."""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class KiCadExporter(Exporter):
    """Export ForgeLab IR to a KiCad PCB. (stub)"""

    tool_name = "kicad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("KiCad export is not implemented yet.")
