"""STL importer: ASCII or binary .stl bytes -> ForgeLab IR.

STL carries only triangle soup and no materials, so the import is one mesh node
(all triangles) plus one object node and a default grey PBR material. Both the
80-byte-header binary format and the ``facet normal / vertex`` ASCII format are
parsed with the standard library only. The mesh name comes from the binary
header or the ASCII ``solid`` line, falling back to the source filename.
"""

from __future__ import annotations

import struct
from pathlib import Path

from forgelab.importers.base import Importer
from forgelab.spec import (
    NODE_MATERIAL,
    NODE_MESH,
    NODE_OBJECT,
    NODE_SCENE,
    DocumentMeta,
    Domain,
    ForgeDocument,
    Material,
    Mesh,
    Node,
    Object3D,
    Primitive,
    Transform,
)
from forgelab.spec.version import SPEC_VERSION

_DEFAULT_MATERIAL_ID = "default_material"


class StlParseError(ValueError):
    """Raised when STL bytes cannot be imported."""


def _default_material() -> Material:
    return Material(name="default", base_color=[0.6, 0.6, 0.6, 1.0], metallic=0.0, roughness=0.5)


def _identity() -> Transform:
    return Transform(
        translation=[0.0, 0.0, 0.0], rotation=[0.0, 0.0, 0.0, 1.0], scale=[1.0, 1.0, 1.0]
    )


def _is_binary(source: bytes) -> bool:
    """Binary iff the size matches the 84 + 50*count layout from the count field."""
    if len(source) < 84:
        return False
    (count,) = struct.unpack_from("<I", source, 80)
    return len(source) == 84 + 50 * count


class StlImporter(Importer):
    """Convert ASCII or binary STL bytes into a ForgeDocument."""

    tool_name = "stl"

    def __init__(self, base_dir: str | Path | None = None, source_name: str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else None
        self.source_name = source_name

    def to_ir(self, source: bytes) -> ForgeDocument:
        if _is_binary(source):
            name, positions = self._parse_binary(source)
        else:
            name, positions = self._parse_ascii(source)
        mesh_name = name or self.source_name or "stl_mesh"

        indices = list(range(len(positions) // 3))
        prim = Primitive(positions=positions, indices=indices, material=_DEFAULT_MATERIAL_ID)

        nodes: list[Node] = [
            Node(id="scene", type=NODE_SCENE, props={"name": "scene"}),
            Node(
                id=_DEFAULT_MATERIAL_ID,
                type=NODE_MATERIAL,
                props=_default_material().model_dump(),
            ),
            Node(
                id=f"{mesh_name}_mesh",
                type=NODE_MESH,
                props=Mesh(name=mesh_name, primitives=[prim]).model_dump(),
            ),
            Node(
                id=mesh_name,
                type=NODE_OBJECT,
                props=Object3D(
                    name=mesh_name, transform=_identity(), mesh=f"{mesh_name}_mesh"
                ).model_dump(),
            ),
        ]
        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.THREED,
            meta=DocumentMeta(name=mesh_name, generator="forgelab-stl"),
            nodes=nodes,
        )

    def _parse_binary(self, source: bytes) -> tuple[str, list[float]]:
        header = source[:80].split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
        name = header[6:].strip() if header.lower().startswith("solid") else header
        (count,) = struct.unpack_from("<I", source, 80)
        positions: list[float] = []
        offset = 84
        for _ in range(count):
            # 50-byte record: normal (3f) + 3 vertices (9f) + uint16 attribute.
            vals = struct.unpack_from("<12fH", source, offset)
            positions.extend(vals[3:12])
            offset += 50
        return name, positions

    def _parse_ascii(self, source: bytes) -> tuple[str, list[float]]:
        text = source.decode("utf-8", errors="replace")
        name = ""
        positions: list[float] = []
        for line in text.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "solid" and len(parts) > 1:
                name = " ".join(parts[1:])
            elif parts[0] == "vertex" and len(parts) >= 4:
                try:
                    positions.extend((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError as exc:
                    raise StlParseError(f"bad vertex line: {line!r}") from exc
        if len(positions) % 9 != 0:
            raise StlParseError("ASCII STL has a vertex count not divisible by 3 per facet")
        return name, positions
