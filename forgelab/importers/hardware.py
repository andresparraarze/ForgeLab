"""Hardware-domain importers (KiCad, Altium, Gerber) -> ForgeLab IR.

These are stubs. Implementations land in dedicated follow-up work.
"""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class KiCadImporter(Importer):
    """Import a KiCad project/schematic into ForgeLab IR. (stub)"""

    tool_name = "kicad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("KiCad import is not implemented yet.")


class AltiumImporter(Importer):
    """Import an Altium design into ForgeLab IR. (stub)"""

    tool_name = "altium"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Altium import is not implemented yet.")


class GerberImporter(Importer):
    """Import Gerber fabrication data into ForgeLab IR. (stub)"""

    tool_name = "gerber"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Gerber import is not implemented yet.")
