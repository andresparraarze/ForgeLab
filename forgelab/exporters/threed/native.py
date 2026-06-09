"""3D / game native-format exporters (Blender .blend, Unreal). (stubs)"""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class BlenderExporter(Exporter):
    """Export ForgeLab IR to a Blender scene. (stub)"""

    tool_name = "blender"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Blender native export is not implemented yet.")


class UnrealExporter(Exporter):
    """Export ForgeLab IR to an Unreal Engine asset. (stub)"""

    tool_name = "unreal"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Unreal Engine export is not implemented yet.")
