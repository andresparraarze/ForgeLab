import pytest

from forgelab.formats import (
    FLOAT,
    UNSIGNED_INT,
    BufferBuilder,
    GltfError,
    decode_accessor,
)


def _gltf_with(builder: BufferBuilder) -> dict:
    return {
        "accessors": builder.accessors,
        "bufferViews": builder.buffer_views,
        "buffers": [builder.buffer()],
    }


def test_buffer_builder_roundtrips_vec3():
    b = BufferBuilder()
    acc = b.add_vec3([-0.5, -0.5, -0.5, 0.5, 0.5, 0.5])
    assert acc == 0
    gltf = _gltf_with(b)
    assert decode_accessor(gltf, 0) == [-0.5, -0.5, -0.5, 0.5, 0.5, 0.5]


def test_buffer_builder_roundtrips_scalar_uint():
    b = BufferBuilder()
    b.add_vec3([0.0, 0.0, 0.0])  # occupy accessor 0 / bufferView 0
    acc = b.add_scalar_uint([0, 1, 2, 3])
    assert acc == 1
    gltf = _gltf_with(b)
    assert decode_accessor(gltf, 1) == [0, 1, 2, 3]


def test_vec3_accessor_has_min_max():
    b = BufferBuilder()
    b.add_vec3([-1.0, -2.0, -3.0, 4.0, 5.0, 6.0])
    assert b.accessors[0]["min"] == [-1.0, -2.0, -3.0]
    assert b.accessors[0]["max"] == [4.0, 5.0, 6.0]
    assert b.accessors[0]["componentType"] == FLOAT
    assert b.accessors[0]["count"] == 2


def test_scalar_accessor_component_type():
    b = BufferBuilder()
    b.add_scalar_uint([7, 8, 9])
    assert b.accessors[0]["componentType"] == UNSIGNED_INT
    assert b.accessors[0]["type"] == "SCALAR"
    assert b.accessors[0]["count"] == 3


def test_bufferviews_are_four_byte_aligned():
    b = BufferBuilder()
    b.add_scalar_uint([1, 2, 3])  # 12 bytes
    b.add_vec3([1.0, 2.0, 3.0])  # next view must start aligned
    assert b.buffer_views[1]["byteOffset"] % 4 == 0


def test_decode_accessor_out_of_range_raises():
    b = BufferBuilder()
    b.add_vec3([0.0, 0.0, 0.0])
    with pytest.raises(GltfError):
        decode_accessor(_gltf_with(b), 5)


def test_decode_rejects_non_base64_uri():
    gltf = {
        "accessors": [{"bufferView": 0, "componentType": FLOAT, "count": 1, "type": "SCALAR"}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 4}],
        "buffers": [{"byteLength": 4, "uri": "cube.bin"}],
    }
    with pytest.raises(GltfError):
        decode_accessor(gltf, 0)


def test_add_vec3_empty_raises():
    with pytest.raises(GltfError):
        BufferBuilder().add_vec3([])


def test_decode_accessor_missing_key_raises_gltf_error():
    gltf = {
        "accessors": [{"type": "VEC3", "count": 1}],  # missing componentType
        "bufferViews": [],
        "buffers": [],
    }
    with pytest.raises(GltfError):
        decode_accessor(gltf, 0)
