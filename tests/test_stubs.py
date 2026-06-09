import pytest

from forgelab.exporters.hardware import AltiumExporter
from forgelab.importers.hardware import AltiumImporter, KiCadImporter
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.importers.threed import BlenderImporter
from forgelab.spec import SPEC_VERSION, DocumentMeta, Domain, ForgeDocument


def test_importer_stub_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        AltiumImporter().to_ir(b"")


def test_exporter_stub_raises_not_implemented():
    doc = ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.HARDWARE,
        meta=DocumentMeta(name="x"),
    )
    with pytest.raises(NotImplementedError):
        AltiumExporter().from_ir(doc)


def test_stub_tool_names_set():
    assert KiCadImporter.tool_name == "kicad"
    assert AltiumImporter.tool_name == "altium"
    assert FreeCADImporter.tool_name == "freecad"
    assert BlenderImporter.tool_name == "blender"
