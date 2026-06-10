from forgelab.core import Registry, default_registry
from forgelab.exporters.base import Exporter
from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


def test_tool_names_reports_import_export_availability():
    class ImpOnly(Importer):
        tool_name = "imp"

        def to_ir(self, source: bytes) -> ForgeDocument:  # pragma: no cover
            raise NotImplementedError

    class ExpOnly(Exporter):
        tool_name = "exp"

        def from_ir(self, document: ForgeDocument) -> bytes:  # pragma: no cover
            raise NotImplementedError

    reg = Registry()
    reg.register_importer(ImpOnly)
    reg.register_exporter(ExpOnly)
    assert reg.tool_names() == {
        "exp": {"import": False, "export": True},
        "imp": {"import": True, "export": False},
    }


def test_default_registry_lists_real_tools():
    names = default_registry().tool_names()
    assert names["kicad"] == {"import": True, "export": True}
    assert names["gltf"]["export"] is True
    assert names["freecad"]["import"] is True
