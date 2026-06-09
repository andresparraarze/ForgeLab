"""Gerber exporter (stub)."""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class GerberExporter(Exporter):
    """Export ForgeLab IR to Gerber fabrication data. (stub)"""

    tool_name = "gerber"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Gerber export is not implemented yet.")
