"""Image textures on threed materials, and the UV coordinates they need.

Every material used to be a flat PBR colour, so nothing could carry real
surface detail. A material now takes a ``base_color_texture`` image path and a
primitive takes ``uvs``, and both exporters were extended with grammar read off
the authoritative sources rather than assumed:

* **glTF** — the Khronos 2.0 schemas. ``baseColorFactor`` is defined as a
  "linear multiplier for the sampled texels of the base color texture", so
  colour and texture MULTIPLY; a textured material keeps its factor.
  ``images`` takes ``uri`` XOR ``bufferView``, so an embedded image is a data
  URI and needs no separate ``mimeType``.
* **Blender** — ``glTF-Blender-IO``, Blender's own glTF importer. It builds the
  Image Texture graph one way for a white factor and another for a tinted one,
  and it flips V (``uvs_gltf_to_blender``: ``u,v -> u,1-v``) because glTF's UV
  origin is top-left and Blender's is bottom-left.

Blender is not installed in this environment, so the generated script is
checked by parsing it and asserting the API calls match that verified grammar —
the standard the rest of the ``blender_script`` suite uses.
"""

import ast
import base64
import hashlib
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from forgelab.core import validate
from forgelab.exporters.threed import BlenderScriptExporter, GltfExporter
from forgelab.formats.gltf import decode_accessor
from forgelab.importers.threed import GltfImporter
from forgelab.spec import (
    DocumentMeta,
    Domain,
    ForgeDocument,
    Material,
    Mesh,
    Node,
    Object3D,
    Primitive,
    Scene,
    Transform,
)
from forgelab.validation import check_threed

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples/threed"
_EXAMPLE = _EXAMPLES / "textured_crate.forge.json"
_TEXTURE = "textures/wood_planks.png"

# SHA-256 of each untextured example's export, captured from the commit BEFORE
# textures existed (checked out and hashed, not taken from the new code). A
# document with no base_color_texture and no uvs must still hash to these.
#
# These values are interpreter-independent: verified byte-identical on CPython
# 3.11.15 and 3.14.5. They are unchanged from when they were first captured --
# a 3.11-only float-summation bug (see tests/test_export_determinism.py) once
# made 3.11 miss three of them, and the fix was to correct the arithmetic, not
# to re-pin the hashes.
_UNTEXTURED_SHAS = {
    "space_station": (
        "dcbd9ed89829344d6bfc6849eda8b66e150ba3f7ca59c399af5d47c1fe0f83b8",
        "90b674990b3b2c73bc507be9370923a0797672b79ff36094f150624dbcabefa9",
    ),
    "torii_gate": (
        "e7644fef5957e67f7131231c531f0da3460fb5ef4779cb6bfe249074e0c70eb8",
        "325c3ac8604a53c2edb16775b569952fcec3bd251aba6f419bbf7dabe3ec740e",
    ),
    "cube": (
        "b1a525c5c12772335eb4c6db30a6ba8a4bdf305e83a4261d1bd9342a6e5fb7ce",
        "aba519d571cff061ef4ebca7359eb40361d6f5041384bc4682a0b5844d1727c7",
    ),
    "organic_handle": (
        "2623827b5ffd18d7bd86c6f165e4feedaf7f745f1712ac13a490d1887b21a608",
        "cde65c0d075eb6cab691d450f7b4df885f77b98ab4fa8dd01d3265991ef67fe5",
    ),
}

# One textured quad: 4 corners, the full 0..1 image, two triangles.
_QUAD_POSITIONS = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0]
_QUAD_UVS = [0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
_QUAD_INDICES = [0, 1, 2, 0, 2, 3]


def _doc(*, texture: str = _TEXTURE, uvs: list[float] | None = _QUAD_UVS,
         base_color: list[float] | None = None) -> ForgeDocument:  # fmt: skip
    material = Material(
        name="surface",
        base_color=base_color or [1.0, 1.0, 1.0, 1.0],
        metallic=0.0,
        roughness=0.8,
        base_color_texture=texture,
    )
    mesh = Mesh(
        name="quad",
        primitives=[
            Primitive(
                positions=_QUAD_POSITIONS,
                indices=_QUAD_INDICES,
                uvs=uvs or [],
                material="mat_surface",
            )
        ],
    )
    obj = Object3D(
        name="Quad",
        mesh="mesh_quad",
        transform=Transform(
            translation=[0.0, 0.0, 0.0], rotation=[0.0, 0.0, 0.0, 1.0], scale=[1.0, 1.0, 1.0]
        ),
    )
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.THREED,
        meta=DocumentMeta(name="tex", generator="test"),
        nodes=[
            Node(id="scene", type="scene", props=Scene(name="S").model_dump()),
            Node(id="mat_surface", type="material", props=material.model_dump()),
            Node(id="mesh_quad", type="mesh", props=mesh.model_dump()),
            Node(id="obj_quad", type="object", props=obj.model_dump()),
        ],
    )


def _gltf(doc: ForgeDocument) -> dict:
    return json.loads(GltfExporter(base_dir=_EXAMPLES).from_ir(doc))


def _script(doc: ForgeDocument) -> str:
    src = BlenderScriptExporter(base_dir=_EXAMPLES).from_ir(doc).decode()
    ast.parse(src)  # every generated script must be valid Python
    return src


# --------------------------------------------------------------- the UV field


def test_uvs_are_uv_pairs_one_per_position():
    prim = Primitive(positions=_QUAD_POSITIONS, uvs=_QUAD_UVS)
    assert len(prim.uvs) // 2 == len(prim.positions) // 3
    with pytest.raises(ValidationError, match="flat"):
        Primitive(positions=_QUAD_POSITIONS, uvs=[0.0, 0.0, 1.0])  # odd length
    with pytest.raises(ValidationError, match="one .u, v. pair per position"):
        Primitive(positions=_QUAD_POSITIONS, uvs=[0.0, 0.0])  # too few pairs


def test_a_primitive_without_uvs_is_still_valid():
    assert Primitive(positions=_QUAD_POSITIONS).uvs == []


def test_uvs_round_trip_through_validate_document():
    doc = _doc()
    revalidated = validate(json.loads(json.dumps(doc.model_dump(mode="json"))))
    (mesh,) = [n for n in revalidated.nodes if n.type == "mesh"]
    assert mesh.props["primitives"][0]["uvs"] == _QUAD_UVS


def test_uvs_survive_the_gltf_round_trip():
    """TEXCOORD_0 goes out and comes back, so the IR identity guarantee still
    holds for a mesh that carries an unwrap."""
    doc = _doc(texture="")
    back = GltfImporter().to_ir(GltfExporter().from_ir(doc))
    (mesh,) = [n for n in back.nodes if n.type == "mesh"]
    assert mesh.props["primitives"][0]["uvs"] == pytest.approx(_QUAD_UVS)


# ------------------------------------------------------------ the glTF export


def test_textured_material_exports_images_samplers_and_textures():
    g = _gltf(_doc())
    assert len(g["images"]) == 1 and len(g["textures"]) == 1 and len(g["samplers"]) == 1
    # textures reference a sampler and an image by index.
    assert g["textures"][0] == {"sampler": 0, "source": 0}
    # Sampler constants from the glTF 2.0 schema: LINEAR / trilinear / REPEAT.
    assert g["samplers"][0] == {
        "magFilter": 9729,
        "minFilter": 9987,
        "wrapS": 10497,
        "wrapT": 10497,
    }


def test_base_color_texture_references_the_texture_by_index():
    pbr = _gltf(_doc())["materials"][0]["pbrMetallicRoughness"]
    assert pbr["baseColorTexture"] == {"index": 0}
    # texCoord defaults to 0 (TEXCOORD_0) and is therefore omitted.
    assert "texCoord" not in pbr["baseColorTexture"]


def test_base_color_factor_is_kept_alongside_the_texture():
    """The Khronos schema calls baseColorFactor a "linear multiplier for the
    sampled texels of the base color texture" — they multiply, so dropping the
    factor would silently change the result."""
    pbr = _gltf(_doc(base_color=[0.5, 0.25, 0.125, 1.0]))["materials"][0]["pbrMetallicRoughness"]
    assert pbr["baseColorFactor"] == [0.5, 0.25, 0.125, 1.0]
    assert "baseColorTexture" in pbr


def test_the_image_is_embedded_as_a_data_uri_holding_the_real_file():
    image = _gltf(_doc())["images"][0]
    assert image["uri"].startswith("data:image/png;base64,")
    # An image carries uri XOR bufferView; mimeType is only required with the
    # latter, and a data URI already names its own type.
    assert "bufferView" not in image and "mimeType" not in image
    embedded = base64.b64decode(image["uri"].split("base64,", 1)[1])
    assert embedded == (_EXAMPLES / _TEXTURE).read_bytes()


def test_uvs_export_as_a_texcoord_0_vec2_accessor():
    g = _gltf(_doc())
    prim = g["meshes"][0]["primitives"][0]
    assert "TEXCOORD_0" in prim["attributes"]
    accessor = g["accessors"][prim["attributes"]["TEXCOORD_0"]]
    assert accessor["type"] == "VEC2"
    assert accessor["componentType"] == 5126  # FLOAT
    assert accessor["count"] == len(_QUAD_UVS) // 2
    assert decode_accessor(g, prim["attributes"]["TEXCOORD_0"]) == pytest.approx(_QUAD_UVS)


def test_several_materials_sharing_one_image_emit_it_once():
    doc = _doc()
    second = Material(name="surface2", base_color=[1.0, 1.0, 1.0, 1.0], base_color_texture=_TEXTURE)
    doc.nodes.insert(2, Node(id="mat_two", type="material", props=second.model_dump()))
    g = _gltf(doc)
    assert len(g["images"]) == 1
    indices = {m["pbrMetallicRoughness"]["baseColorTexture"]["index"] for m in g["materials"]}
    assert indices == {0}


def test_an_unreadable_texture_path_names_the_file_and_the_base_dir():
    with pytest.raises(ValueError, match="nope.png"):
        GltfExporter(base_dir=_EXAMPLES).from_ir(_doc(texture="nope.png"))


# --------------------------------------------------------- the Blender export


def test_blender_script_loads_the_image_and_wires_an_image_texture_node():
    src = _script(_doc())
    assert "bpy.data.images.load(" in src
    assert str((_EXAMPLES / _TEXTURE).resolve()) in src  # absolute: runs anywhere
    assert 'nodes.new("ShaderNodeTexImage")' in src
    assert "_tex.image = _img" in src


def test_a_white_base_color_links_the_texture_straight_to_base_color():
    """What Blender's own glTF importer does when baseColorFactor is white: no
    mix node, the texture drives Base Color directly."""
    src = _script(_doc())
    assert 'links.new(bsdf.inputs["Base Color"], _tex.outputs["Color"])' in src
    assert "ShaderNodeMix" not in src


def test_a_tinted_base_color_multiplies_through_a_mix_node():
    """Matching glTF's multiply semantics, and built the way glTF-Blender-IO
    builds it — including addressing the RGBA Mix node's colour sockets by
    index, since its A/B/Result names are shared with float sockets."""
    src = _script(_doc(base_color=[0.5, 0.25, 0.125, 1.0]))
    assert 'nodes.new("ShaderNodeMix")' in src
    assert '_mix.data_type = "RGBA"' in src
    assert '_mix.blend_type = "MULTIPLY"' in src
    assert '_mix.inputs["Factor"].default_value = 1.0' in src
    assert "_mix.inputs[7].default_value = (0.5, 0.25, 0.125, 1.0)" in src
    assert "links.new(_mix.inputs[6], _tex.outputs['Color'])" in src
    assert 'links.new(bsdf.inputs["Base Color"], _mix.outputs[2])' in src


def test_blender_script_creates_a_uv_layer_per_loop():
    src = _script(_doc())
    assert 'mesh.uv_layers.new(name="UVMap")' in src
    # UVs live per face corner in Blender, so they are assigned by loop.
    assert "for _loop in mesh.loops:" in src
    assert "_uv_layer.data[_loop.index].uv = _uvs[_loop.vertex_index]" in src


def test_blender_v_coordinate_is_flipped_against_gltf():
    """glTF's UV origin is top-left, Blender's bottom-left. Blender's own glTF
    importer converts with ``u,v -> u,1-v``; without the same flip here every
    texture would land mirrored vertically against the .gltf export."""
    src = _script(_doc())
    uv_line = next(line for line in src.splitlines() if line.startswith("_uvs = "))
    emitted = [(float(u), float(v)) for u, v in re.findall(r"\(([-\d.]+), ([-\d.]+)\)", uv_line)]
    ir_pairs = list(zip(_QUAD_UVS[0::2], _QUAD_UVS[1::2], strict=True))
    assert emitted == [(u, 1.0 - v) for u, v in ir_pairs]
    assert emitted != ir_pairs  # the fixture genuinely distinguishes the two


def test_an_authored_unwrap_suppresses_primitive_detection():
    """A cube-shaped mesh is normally rebuilt with primitive_cube_add, which
    would substitute Blender's default UV layout for the authored one."""
    doc = validate(json.loads(_EXAMPLE.read_text()))
    src = _script(doc)
    assert "primitive_cube_add" not in src
    assert "from_pydata" in src and 'uv_layers.new(name="UVMap")' in src


# ------------------------------------------------------- untextured unchanged


@pytest.mark.parametrize("name", sorted(_UNTEXTURED_SHAS))
def test_untextured_examples_export_byte_identically_in_both_formats(name):
    doc = validate(json.loads((_EXAMPLES / f"{name}.forge.json").read_text()))
    gltf_sha, blender_sha = _UNTEXTURED_SHAS[name]
    assert hashlib.sha256(GltfExporter().from_ir(doc)).hexdigest() == gltf_sha
    assert hashlib.sha256(BlenderScriptExporter().from_ir(doc)).hexdigest() == blender_sha


def test_an_untextured_export_mentions_no_texture_machinery():
    doc = validate(json.loads((_EXAMPLES / "cube.forge.json").read_text()))
    g = json.loads(GltfExporter().from_ir(doc))
    assert not any(k in g for k in ("images", "samplers", "textures"))
    assert "TEXCOORD_0" not in json.dumps(g)
    src = BlenderScriptExporter().from_ir(doc).decode()
    assert "ShaderNodeTexImage" not in src and "uv_layers" not in src


# ------------------------------------------------------------- the validation


def test_a_texture_without_uvs_is_a_validation_error():
    errors, _warnings = check_threed(_doc(uvs=None))
    assert len(errors) == 1
    message = errors[0]
    assert "mat_surface" in message and "mesh_quad" in message
    assert "no UV coordinates" in message
    assert _TEXTURE in message  # names the texture that has nowhere to go


def test_a_texture_with_uvs_validates_clean():
    assert check_threed(_doc()) == ([], [])


def test_uvs_without_a_texture_are_not_flagged():
    """An unwrap the document is not using yet is harmless."""
    assert check_threed(_doc(texture="")) == ([], [])


def test_a_primitive_naming_a_missing_material_is_an_error():
    doc = _doc()
    for node in doc.nodes:
        if node.type == "mesh":
            node.props["primitives"][0]["material"] = "surface"  # the name, not the id
    errors, _warnings = check_threed(doc)
    assert any("'surface'" in e and "mat_surface" in e for e in errors), errors


def test_check_threed_ignores_other_domains():
    blinky = _EXAMPLES.parent / "hardware/blinky.forge.json"
    assert check_threed(validate(json.loads(blinky.read_text()))) == ([], [])


# ------------------------------------------------------------ worked example


def test_textured_crate_example_validates():
    doc = validate(json.loads(_EXAMPLE.read_text()))
    assert check_threed(doc) == ([], [])
    (material,) = [n for n in doc.nodes if n.type == "material"]
    assert material.props["base_color_texture"] == _TEXTURE
    assert (_EXAMPLES / _TEXTURE).is_file()


def test_textured_crate_has_cube_projection_uvs():
    """Cube projection: 6 faces x 4 unshared corners, each face covering the
    whole image, so every side shows the full planks pattern."""
    doc = validate(json.loads(_EXAMPLE.read_text()))
    (mesh,) = [n for n in doc.nodes if n.type == "mesh"]
    prim = mesh.props["primitives"][0]
    assert len(prim["positions"]) // 3 == 24  # 6 * 4, corners not shared
    assert len(prim["indices"]) // 3 == 12  # 6 * 2 triangles
    pairs = list(zip(prim["uvs"][0::2], prim["uvs"][1::2], strict=True))
    assert len(pairs) == 24
    corners = {(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)}
    for face in range(6):
        assert set(pairs[face * 4 : face * 4 + 4]) == corners


def test_textured_crate_exports_to_both_formats():
    doc = validate(json.loads(_EXAMPLE.read_text()))

    g = _gltf(doc)
    assert g["textures"] == [{"sampler": 0, "source": 0}]
    assert g["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] == {"index": 0}
    prim = g["meshes"][0]["primitives"][0]
    uvs = decode_accessor(g, prim["attributes"]["TEXCOORD_0"])
    assert len(uvs) == 48  # 24 pairs
    assert (
        base64.b64decode(g["images"][0]["uri"].split("base64,", 1)[1])
        == (_EXAMPLES / _TEXTURE).read_bytes()
    )

    src = _script(doc)  # ast.parse inside
    assert 'nodes.new("ShaderNodeTexImage")' in src
    assert 'mesh.uv_layers.new(name="UVMap")' in src
