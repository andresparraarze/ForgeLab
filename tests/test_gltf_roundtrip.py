from pathlib import Path

from forgelab.exporters.threed.gltf import GltfExporter
from forgelab.importers.threed.gltf import GltfImporter

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "threed" / "cube.gltf"


def test_import_export_import_is_identity():
    doc1 = GltfImporter().to_ir(FIXTURE.read_bytes())
    gltf_bytes = GltfExporter().from_ir(doc1)
    doc2 = GltfImporter().to_ir(gltf_bytes)
    assert doc2 == doc1


def test_roundtrip_preserves_geometry_and_material():
    doc1 = GltfImporter().to_ir(FIXTURE.read_bytes())
    doc2 = GltfImporter().to_ir(GltfExporter().from_ir(doc1))
    types1 = sorted(n.type for n in doc1.nodes)
    types2 = sorted(n.type for n in doc2.nodes)
    assert types1 == types2
    assert any(n.type == "material" for n in doc2.nodes)
    assert any(n.type == "mesh" for n in doc2.nodes)


def test_gltf_registered_in_default_registry():
    from forgelab.core import default_registry

    reg = default_registry()
    assert reg.get_importer("gltf").__name__ == "GltfImporter"
    assert reg.get_exporter("gltf").__name__ == "GltfExporter"
