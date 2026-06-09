"""Hardware-domain exporters (KiCad, Altium, Gerber) from ForgeLab IR. (stubs)"""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class KiCadExporter(Exporter):
    """Export ForgeLab IR to a KiCad project. (stub)"""

    tool_name = "kicad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("KiCad export is not implemented yet.")


class AltiumExporter(Exporter):
    """Export ForgeLab IR to an Altium design. (stub)"""

    tool_name = "altium"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Altium export is not implemented yet.")


class GerberExporter(Exporter):
    """Export ForgeLab IR to Gerber fabrication data. (stub)"""

    tool_name = "gerber"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Gerber export is not implemented yet.")
