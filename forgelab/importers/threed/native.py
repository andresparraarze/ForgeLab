"""3D / game native-format importers (Blender .blend, Unreal). (stubs)"""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class BlenderImporter(Importer):
    """Import a Blender scene into ForgeLab IR. (stub)"""

    implemented = False
    tool_name = "blender"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Blender native import is not implemented yet.")


class UnrealImporter(Importer):
    """Import an Unreal Engine asset into ForgeLab IR. (stub)"""

    implemented = False
    tool_name = "unreal"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Unreal Engine import is not implemented yet.")
