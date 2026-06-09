"""KiCad importer (stub — implemented in a later task)."""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class KiCadImporter(Importer):
    """Import a KiCad PCB into ForgeLab IR. (stub)"""

    tool_name = "kicad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("KiCad import is not implemented yet.")
