import json
from pathlib import Path

import pytest

from forgelab.exporters.threed.gltf import GltfExporter
from forgelab.exporters.threed.native import BlenderExporter
from forgelab.formats.gltf import decode_accessor
from forgelab.importers.threed.gltf import GltfImporter
from forgelab.sdk import load
from forgelab.spec import SPEC_VERSION

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


def _threed_doc(material_ref: str = "mat_red", mesh_ref: str = "mesh_cube"):
    return load(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "threed",
            "meta": {"name": "scene", "generator": "test"},
            "nodes": [
                {
                    "id": "mat_red",
                    "type": "material",
                    "props": {"name": "vermilion", "base_color": [1.0, 0.0, 0.0, 1.0]},
                },
                {
                    "id": "mesh_cube",
                    "type": "mesh",
                    "props": {
                        "name": "cube",
                        "primitives": [{"positions": [0.0, 0.0, 0.0], "material": material_ref}],
                    },
                },
                {
                    "id": "obj_cube",
                    "type": "object",
                    "props": {
                        "name": "Cube",
                        "transform": {
                            "translation": [0.0, 0.0, 0.0],
                            "rotation": [0.0, 0.0, 0.0, 1.0],
                            "scale": [1.0, 1.0, 1.0],
                        },
                        "mesh": mesh_ref,
                    },
                },
            ],
        }
    )


def test_blender_export_suggests_gltf():
    with pytest.raises(NotImplementedError, match="gltf"):
        BlenderExporter().from_ir(_threed_doc())


def test_gltf_export_unknown_material_ref_is_clear():
    # 'vermilion' is the material's display name, not its node id 'mat_red'.
    with pytest.raises(ValueError, match="material") as exc:
        GltfExporter().from_ir(_threed_doc(material_ref="vermilion"))
    msg = str(exc.value)
    assert "vermilion" in msg and "id" in msg


def test_gltf_export_unknown_mesh_ref_is_clear():
    with pytest.raises(ValueError, match="mesh") as exc:
        GltfExporter().from_ir(_threed_doc(mesh_ref="Cube"))
    msg = str(exc.value)
    assert "Cube" in msg and "id" in msg


# A thin tower far taller (Y) than it is wide (X) or deep (Z), authored Y-up.
_TOWER_POSITIONS = [
    -0.5,
    0.0,
    -0.5,
    0.5,
    0.0,
    -0.5,
    0.5,
    0.0,
    0.5,
    -0.5,
    0.0,
    0.5,
    -0.5,
    10.0,
    -0.5,
    0.5,
    10.0,
    -0.5,
    0.5,
    10.0,
    0.5,
    -0.5,
    10.0,
    0.5,
]


def _tower_doc():
    return load(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "threed",
            "meta": {"name": "tower", "generator": "test"},
            "nodes": [
                {
                    "id": "tower_mesh",
                    "type": "mesh",
                    "props": {
                        "name": "Tower",
                        "primitives": [{"positions": list(_TOWER_POSITIONS)}],
                    },
                },
                {
                    "id": "tower_obj",
                    "type": "object",
                    "props": {
                        "name": "Tower",
                        "transform": {
                            "translation": [0.0, 0.0, 0.0],
                            "rotation": [0.0, 0.0, 0.0, 1.0],
                            "scale": [1.0, 1.0, 1.0],
                        },
                        "mesh": "tower_mesh",
                    },
                },
            ],
        }
    )


def _exported_positions(gltf: dict) -> list[float]:
    accessor = gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    return decode_accessor(gltf, accessor)


def test_export_is_y_up_vertical_axis_stays_y():
    # ForgeLab's threed IR is Y-up (glTF's native convention); the exporter
    # passes coordinates straight through. A Y-tall tower must therefore export
    # with Y as its largest extent so Blender's Y-up->Z-up importer lands it
    # upright rather than tipped on its side.
    gltf = json.loads(GltfExporter().from_ir(_tower_doc()))
    flat = _exported_positions(gltf)
    xs, ys, zs = flat[0::3], flat[1::3], flat[2::3]
    span = lambda v: max(v) - min(v)  # noqa: E731
    assert span(ys) > span(xs)
    assert span(ys) > span(zs)


def test_export_does_not_rotate_coordinates():
    # No up-axis conversion on export: positions are emitted exactly as authored.
    gltf = json.loads(GltfExporter().from_ir(_tower_doc()))
    assert _exported_positions(gltf) == pytest.approx(list(_TOWER_POSITIONS))


def test_gltf_registered_in_default_registry():
    from forgelab.core import default_registry

    reg = default_registry()
    assert reg.get_importer("gltf").__name__ == "GltfImporter"
    assert reg.get_exporter("gltf").__name__ == "GltfExporter"
