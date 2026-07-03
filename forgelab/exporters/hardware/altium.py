"""Altium exporter (stub)."""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class AltiumExporter(Exporter):
    """Export ForgeLab IR to an Altium design. (stub)"""

    implemented = False
    tool_name = "altium"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Altium export is not implemented yet.")
