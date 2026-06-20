"""OBJ and STL importers -> ForgeLab threed IR."""

import struct

from forgelab.core import default_registry, validate
from forgelab.importers.threed import ObjImporter, StlImporter
from forgelab.mcp import tools

_REG = default_registry()


def _nodes(doc, ntype):
    return [n for n in doc["nodes"] if n["type"] == ntype]


# --------------------------------------------------------------------------- #
# OBJ
# --------------------------------------------------------------------------- #
def _write_obj(tmp_path, obj_text, mtl_text=None):
    if mtl_text is not None:
        (tmp_path / "model.mtl").write_text(mtl_text)
    path = tmp_path / "model.obj"
    path.write_text(obj_text)
    return path


_MTL = """newmtl red
Kd 0.9 0.1 0.1
Ns 800
Pm 0.0
newmtl steel
Kd 0.5 0.5 0.55
Ns 200
Pm 1.0
"""

_OBJ_TWO_OBJECTS = """mtllib model.mtl
o boxA
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
usemtl red
f 1 2 3 4
o triB
v 2 0 0
v 3 0 0
v 2 1 0
usemtl steel
f 5 6 7
"""


def test_obj_multiple_objects_and_materials(tmp_path):
    path = _write_obj(tmp_path, _OBJ_TWO_OBJECTS, _MTL)
    doc = tools.import_file(tool="obj", file_path=str(path))

    assert tools.validate_document(doc)["valid"] is True
    assert {n["id"] for n in _nodes(doc, "object")} == {"boxA", "triB"}
    assert len(_nodes(doc, "mesh")) == 2
    mats = {n["id"] for n in _nodes(doc, "material")}
    assert mats == {"red", "steel"}

    red = next(n for n in _nodes(doc, "material") if n["id"] == "red")
    assert red["props"]["base_color"] == [0.9, 0.1, 0.1, 1.0]
    assert abs(red["props"]["roughness"] - 0.2) < 1e-6  # Ns 800 -> 1 - 0.8
    steel = next(n for n in _nodes(doc, "material") if n["id"] == "steel")
    assert steel["props"]["metallic"] == 1.0


def test_obj_quad_is_fan_triangulated(tmp_path):
    path = _write_obj(tmp_path, _OBJ_TWO_OBJECTS, _MTL)
    doc = tools.import_file(tool="obj", file_path=str(path))
    box = next(n for n in _nodes(doc, "mesh") if n["id"] == "boxA_mesh")
    indices = box["props"]["primitives"][0]["indices"]
    assert len(indices) == 6  # one quad -> two triangles


def test_obj_without_mtl_uses_default_grey():
    obj = "o thing\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    doc = ObjImporter().to_ir(obj.encode()).model_dump(mode="json")
    assert tools.validate_document(doc)["valid"] is True
    mats = _nodes(doc, "material")
    assert len(mats) == 1
    assert mats[0]["id"] == "default_material"
    assert mats[0]["props"]["base_color"] == [0.6, 0.6, 0.6, 1.0]


def test_obj_negative_indices(tmp_path):
    obj = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\n"
    doc = ObjImporter().to_ir(obj.encode()).model_dump(mode="json")
    assert tools.validate_document(doc)["valid"] is True
    mesh = _nodes(doc, "mesh")[0]
    assert len(mesh["props"]["primitives"][0]["positions"]) == 9


def test_obj_roundtrips_to_gltf(tmp_path):
    path = _write_obj(tmp_path, _OBJ_TWO_OBJECTS, _MTL)
    doc = validate(tools.import_file(tool="obj", file_path=str(path)))
    data = _REG.get_exporter("gltf")().from_ir(doc)
    assert data and b'"asset"' in data


# --------------------------------------------------------------------------- #
# STL
# --------------------------------------------------------------------------- #
_ASCII_STL = """solid widget
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 1 0 0
  vertex 0 1 0
 endloop
endfacet
facet normal 0 0 1
 outer loop
  vertex 1 0 0
  vertex 1 1 0
  vertex 0 1 0
 endloop
endfacet
endsolid widget
"""


def _binary_stl(name: bytes, triangles: list[tuple]) -> bytes:
    out = name.ljust(80, b"\x00") + struct.pack("<I", len(triangles))
    for tri in triangles:
        # normal (3f) + 3 vertices (9f) + attribute uint16
        out += struct.pack("<12fH", 0.0, 0.0, 1.0, *tri[0], *tri[1], *tri[2], 0)
    return out


def test_stl_ascii():
    doc = StlImporter().to_ir(_ASCII_STL.encode()).model_dump(mode="json")
    assert tools.validate_document(doc)["valid"] is True
    mesh = _nodes(doc, "mesh")[0]
    assert mesh["props"]["name"] == "widget"
    assert len(mesh["props"]["primitives"][0]["indices"]) == 6  # 2 facets


def test_stl_binary_header_name():
    data = _binary_stl(b"binary cube demo", [((0, 0, 0), (1, 0, 0), (0, 1, 0))])
    doc = StlImporter().to_ir(data).model_dump(mode="json")
    assert tools.validate_document(doc)["valid"] is True
    mesh = _nodes(doc, "mesh")[0]
    assert mesh["props"]["name"] == "binary cube demo"


def test_stl_binary_multi_triangle_mesh():
    tris = [
        ((0, 0, 0), (1, 0, 0), (0, 1, 0)),
        ((1, 0, 0), (1, 1, 0), (0, 1, 0)),
        ((0, 0, 1), (1, 0, 1), (0, 1, 1)),
    ]
    data = _binary_stl(b"multi", tris)
    doc = StlImporter().to_ir(data).model_dump(mode="json")
    mesh = _nodes(doc, "mesh")[0]
    prim = mesh["props"]["primitives"][0]
    assert len(prim["positions"]) == 3 * 9  # 3 triangles * 3 verts * 3 coords
    assert len(prim["indices"]) == 9
    # default grey material, single object
    assert _nodes(doc, "material")[0]["id"] == "default_material"
    assert len(_nodes(doc, "object")) == 1


def test_stl_filename_used_when_header_blank(tmp_path):
    data = _binary_stl(b"", [((0, 0, 0), (1, 0, 0), (0, 1, 0))])
    path = tmp_path / "gizmo.stl"
    path.write_bytes(data)
    doc = tools.import_file(tool="stl", file_path=str(path))
    mesh = _nodes(doc, "mesh")[0]
    assert mesh["props"]["name"] == "gizmo"


# --------------------------------------------------------------------------- #
# registry / list_formats
# --------------------------------------------------------------------------- #
def test_importers_registered():
    assert _REG.get_importer("obj") is ObjImporter
    assert _REG.get_importer("stl") is StlImporter


def test_list_formats_includes_obj_and_stl():
    formats = tools.list_formats()
    assert formats["obj"] == {"import": True, "export": False}
    assert formats["stl"] == {"import": True, "export": False}
