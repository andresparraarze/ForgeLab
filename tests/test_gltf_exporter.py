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


def test_objects_nested_under_scene_node_are_exported():
    # Live-testing regression (Blender): object nodes supplied as children of
    # the scene node — instead of at the document top level — were dropped.
    import json

    from forgelab.spec import SPEC_VERSION, ForgeDocument

    doc = ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "threed",
            "meta": {"name": "scene", "generator": "test"},
            "nodes": [
                {
                    "id": "scene",
                    "type": "scene",
                    "props": {"name": "scene"},
                    "children": [
                        {
                            "id": "Cube",
                            "type": "object",
                            "props": {
                                "name": "Cube",
                                "transform": {
                                    "translation": [0, 0, 0],
                                    "rotation": [0, 0, 0, 1],
                                    "scale": [1, 1, 1],
                                },
                            },
                        }
                    ],
                }
            ],
        }
    )
    gltf = json.loads(GltfExporter().from_ir(doc))
    assert [n["name"] for n in gltf.get("nodes", [])] == ["Cube"]
    assert gltf["scenes"][0]["nodes"] == [0]


def _material_doc(base_color):
    from forgelab.spec import SPEC_VERSION, ForgeDocument

    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "threed",
            "meta": {"name": "scene", "generator": "test"},
            "nodes": [
                {
                    "id": "mat_glass",
                    "type": "material",
                    "props": {"name": "glass", "base_color": base_color},
                }
            ],
        }
    )


def test_translucent_material_exports_alpha_mode_blend():
    # Live-testing regression (Blender import): baseColorFactor alpha 0.3 was
    # written but alphaMode never set, so per the glTF spec every compliant
    # viewer rendered the material fully opaque.
    gltf = json.loads(GltfExporter().from_ir(_material_doc([0.2, 0.4, 0.9, 0.3])))
    mat = gltf["materials"][0]
    assert mat["alphaMode"] == "BLEND"
    assert mat["pbrMetallicRoughness"]["baseColorFactor"] == [0.2, 0.4, 0.9, 0.3]


def test_opaque_material_exports_no_alpha_mode():
    # Alpha 1.0 must leave alphaMode unset: glTF defaults to OPAQUE, which is
    # correct, and the pre-fix output for opaque materials must not change.
    gltf = json.loads(GltfExporter().from_ir(_material_doc([0.2, 0.4, 0.9, 1.0])))
    mat = gltf["materials"][0]
    assert "alphaMode" not in mat
    assert mat["pbrMetallicRoughness"]["baseColorFactor"] == [0.2, 0.4, 0.9, 1.0]


def test_rgb_only_base_color_is_opaque_with_no_alpha_mode():
    # [r, g, b] is shorthand for [r, g, b, 1.0]: fully opaque, no override.
    gltf = json.loads(GltfExporter().from_ir(_material_doc([0.2, 0.4, 0.9])))
    mat = gltf["materials"][0]
    assert "alphaMode" not in mat
    assert mat["pbrMetallicRoughness"]["baseColorFactor"] == [0.2, 0.4, 0.9, 1.0]
