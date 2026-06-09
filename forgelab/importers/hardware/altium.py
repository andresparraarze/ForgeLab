"""Altium importer (stub)."""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class AltiumImporter(Importer):
    """Import an Altium design into ForgeLab IR. (stub)"""

    tool_name = "altium"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Altium import is not implemented yet.")
