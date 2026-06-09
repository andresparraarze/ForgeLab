import json
from pathlib import Path

from forgelab.exporters.threed.gltf import GltfExporter
from forgelab.importers.threed.gltf import GltfImporter

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "threed" / "cube.gltf"


def _export_bytes():
    doc = GltfImporter().to_ir(FIXTURE.read_bytes())
    return GltfExporter().from_ir(doc)


def test_export_is_valid_gltf_json():
    data = json.loads(_export_bytes())
    assert data["asset"]["version"] == "2.0"
    assert data["scene"] == 0
    assert len(data["scenes"]) == 1
    assert len(data["materials"]) == 1
    assert len(data["meshes"]) == 1
    assert len(data["nodes"]) == 1


def test_export_material_is_red():
    data = json.loads(_export_bytes())
    pbr = data["materials"][0]["pbrMetallicRoughness"]
    assert pbr["baseColorFactor"] == [0.8, 0.1, 0.1, 1.0]
    assert pbr["metallicFactor"] == 0.0


def test_export_mesh_primitive_wiring():
    data = json.loads(_export_bytes())
    prim = data["meshes"][0]["primitives"][0]
    assert "POSITION" in prim["attributes"]
    assert "indices" in prim
    assert prim["material"] == 0
    assert data["nodes"][0]["mesh"] == 0


def test_export_buffer_decodes_back_to_cube():
    from forgelab.formats import decode_accessor

    data = json.loads(_export_bytes())
    prim = data["meshes"][0]["primitives"][0]
    positions = decode_accessor(data, prim["attributes"]["POSITION"])
    indices = decode_accessor(data, prim["indices"])
    assert len(positions) == 24
    assert len(indices) == 36
    assert positions[:3] == [-0.5, -0.5, -0.5]
