"""glTF accessor/buffer codec — a neutral primitive shared by the glTF
importer and exporter.

glTF stores geometry as binary buffers referenced indirectly through
accessors -> bufferViews -> buffers. ``decode_accessor`` reads a flat list of
numbers out of that indirection; ``BufferBuilder`` does the reverse, packing
arrays into a single base64-embedded buffer with the matching bufferViews and
accessors. Only the component/accessor types the 3D domain needs are supported.
"""

from __future__ import annotations

import base64
import struct

FLOAT = 5126
UNSIGNED_INT = 5125
UNSIGNED_SHORT = 5123
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963

_COMPONENT_FORMAT = {FLOAT: "f", UNSIGNED_INT: "I", UNSIGNED_SHORT: "H"}
_COMPONENT_SIZE = {FLOAT: 4, UNSIGNED_INT: 4, UNSIGNED_SHORT: 2}
_TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


class GltfError(ValueError):
    """Raised on malformed or unsupported glTF data."""


def _decode_data_uri(uri: str) -> bytes:
    marker = "base64,"
    pos = uri.find(marker)
    if not uri.startswith("data:") or pos == -1:
        raise GltfError("buffer uri must be a base64 data URI")
    return base64.b64decode(uri[pos + len(marker) :])


def decode_accessor(gltf: dict, index: int) -> list[float | int]:
    """Decode glTF accessor ``index`` into a flat list of numbers."""
    accessors = gltf.get("accessors", [])
    if index < 0 or index >= len(accessors):
        raise GltfError(f"accessor index {index} out of range")
    acc = accessors[index]
    comp_type = acc["componentType"]
    acc_type = acc["type"]
    count = acc["count"]
    if comp_type not in _COMPONENT_FORMAT:
        raise GltfError(f"unsupported componentType {comp_type}")
    if acc_type not in _TYPE_COMPONENTS:
        raise GltfError(f"unsupported accessor type {acc_type!r}")

    n_comp = _TYPE_COMPONENTS[acc_type]
    view = gltf["bufferViews"][acc["bufferView"]]
    buffer = gltf["buffers"][view["buffer"]]
    data = _decode_data_uri(buffer["uri"])

    fmt = "<" + _COMPONENT_FORMAT[comp_type]
    size = _COMPONENT_SIZE[comp_type]
    base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)

    out: list[float | int] = []
    for i in range(count * n_comp):
        (value,) = struct.unpack_from(fmt, data, base + i * size)
        out.append(value)
    return out


class BufferBuilder:
    """Accumulate accessors into one base64-embedded glTF buffer."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._length = 0
        self.buffer_views: list[dict] = []
        self.accessors: list[dict] = []

    def _append(self, data: bytes, target: int) -> int:
        pad = (-self._length) % 4
        if pad:
            self._chunks.append(b"\x00" * pad)
            self._length += pad
        offset = self._length
        self._chunks.append(data)
        self._length += len(data)
        self.buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": offset,
                "byteLength": len(data),
                "target": target,
            }
        )
        return len(self.buffer_views) - 1

    def add_vec3(self, values: list[float]) -> int:
        """Add flat xyz floats as a VEC3/FLOAT accessor; return its index."""
        if len(values) % 3 != 0:
            raise GltfError("VEC3 data length must be a multiple of 3")
        data = b"".join(struct.pack("<f", v) for v in values)
        view = self._append(data, ARRAY_BUFFER)
        xs, ys, zs = values[0::3], values[1::3], values[2::3]
        self.accessors.append(
            {
                "bufferView": view,
                "componentType": FLOAT,
                "count": len(values) // 3,
                "type": "VEC3",
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)],
            }
        )
        return len(self.accessors) - 1

    def add_scalar_uint(self, values: list[int]) -> int:
        """Add ints as a SCALAR/UNSIGNED_INT accessor; return its index."""
        data = b"".join(struct.pack("<I", v) for v in values)
        view = self._append(data, ELEMENT_ARRAY_BUFFER)
        self.accessors.append(
            {
                "bufferView": view,
                "componentType": UNSIGNED_INT,
                "count": len(values),
                "type": "SCALAR",
            }
        )
        return len(self.accessors) - 1

    def buffer(self) -> dict:
        """Return the assembled glTF buffer object (base64 data URI)."""
        data = b"".join(self._chunks)
        uri = "data:application/octet-stream;base64," + base64.b64encode(data).decode()
        return {"byteLength": len(data), "uri": uri}
