import pytest

from forgelab.core import UnknownToolError
from forgelab.core.registry import Registry
from forgelab.exporters.base import Exporter
from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class _FakeImporter(Importer):
    tool_name = "fake"

    def to_ir(self, source: bytes) -> ForgeDocument:  # pragma: no cover - trivial
        raise NotImplementedError


def test_registry_register_and_get():
    reg = Registry()
    reg.register_importer(_FakeImporter)
    assert reg.get_importer("fake") is _FakeImporter


def test_registry_unknown_tool_raises():
    reg = Registry()
    with pytest.raises(UnknownToolError):
        reg.get_importer("missing")


def test_importer_is_abstract():
    with pytest.raises(TypeError):
        Importer()  # type: ignore[abstract]


def test_exporter_is_abstract():
    with pytest.raises(TypeError):
        Exporter()  # type: ignore[abstract]
