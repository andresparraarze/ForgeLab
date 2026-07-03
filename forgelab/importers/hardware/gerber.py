"""Gerber importer (stub)."""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class GerberImporter(Importer):
    """Import Gerber fabrication data into ForgeLab IR. (stub)"""

    implemented = False
    tool_name = "gerber"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Gerber import is not implemented yet.")
