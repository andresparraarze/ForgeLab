import json
from pathlib import Path

import pytest

from forgelab.importers.threed.gltf import GltfImporter, GltfParseError
from forgelab.spec import (
    NODE_MATERIAL,
    NODE_MESH,
    NODE_OBJECT,
    NODE_SCENE,
    Material,
    Mesh,
    Object3D,
)

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "threed" / "cube.gltf"


def _import():
    return GltfImporter().to_ir(FIXTURE.read_bytes())


def test_fixture_is_valid_json_gltf():
    data = json.loads(FIXTURE.read_text())
    assert data["asset"]["version"] == "2.0"


def test_import_has_scene_material_mesh_object():
    doc = _import()
    by_type = {}
    for n in doc.nodes:
        by_type.setdefault(n.type, []).append(n)
    assert len(by_type[NODE_SCENE]) == 1
    assert len(by_type[NODE_MATERIAL]) == 1
    assert len(by_type[NODE_MESH]) == 1
    assert len(by_type[NODE_OBJECT]) == 1


def test_import_material_is_red():
    doc = _import()
    mat_node = next(n for n in doc.nodes if n.type == NODE_MATERIAL)
    mat = Material.model_validate(mat_node.props)
    assert mat.name == "RedMaterial"
    assert mat.base_color == [0.8, 0.1, 0.1, 1.0]
    assert mat.metallic == 0.0
    assert mat.roughness == 0.5
    assert mat_node.id == "RedMaterial"


def test_import_mesh_geometry_decoded():
    doc = _import()
    mesh_node = next(n for n in doc.nodes if n.type == NODE_MESH)
    mesh = Mesh.model_validate(mesh_node.props)
    prim = mesh.primitives[0]
    assert len(prim.positions) == 24
    assert prim.positions[:3] == [-0.5, -0.5, -0.5]
    assert len(prim.indices) == 36
    assert prim.material == "RedMaterial"


def test_import_object_references_mesh_with_default_transform():
    doc = _import()
    obj_node = next(n for n in doc.nodes if n.type == NODE_OBJECT)
    obj = Object3D.model_validate(obj_node.props)
    assert obj.name == "Cube"
    assert obj.mesh == "CubeMesh"
    assert obj.transform.translation == [0.0, 0.0, 0.0]
    assert obj.transform.rotation == [0.0, 0.0, 0.0, 1.0]
    assert obj.transform.scale == [1.0, 1.0, 1.0]


def test_import_garbage_raises_parse_error():
    with pytest.raises(GltfParseError):
        GltfImporter().to_ir(b"not json")
    with pytest.raises(GltfParseError):
        GltfImporter().to_ir(b'{"asset": {"version": "1.0"}}')


def test_import_out_of_range_node_index_raises():
    bad = b'{"asset":{"version":"2.0"},"scene":0,"scenes":[{"name":"S","nodes":[99]}],"nodes":[]}'
    with pytest.raises(GltfParseError):
        GltfImporter().to_ir(bad)


def test_import_primitive_bad_accessor_raises_parse_error():
    bad = (
        b'{"asset":{"version":"2.0"},"scene":0,'
        b'"scenes":[{"name":"S","nodes":[0]}],'
        b'"nodes":[{"name":"N","mesh":0}],'
        b'"meshes":[{"name":"M","primitives":[{"attributes":{"POSITION":5}}]}]}'
    )
    with pytest.raises(GltfParseError):
        GltfImporter().to_ir(bad)
