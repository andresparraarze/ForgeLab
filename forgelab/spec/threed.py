"""Typed 3D / game vocabulary for the ForgeLab IR.

These models describe glTF-style scene concepts — materials, meshes, geometry
primitives, transforms, and scene objects. Like the hardware vocabulary they are
not a new document root: they serialize into the generic ``Node`` graph. Scene
hierarchy is expressed with ``Node.children`` (objects nest inside objects);
meshes and materials are flat, id-referenced top-level nodes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

NODE_SCENE = "scene"
NODE_OBJECT = "object"
NODE_MESH = "mesh"
NODE_MATERIAL = "material"


class Scene(BaseModel):
    """A glTF scene: a named container for the object graph."""

    model_config = ConfigDict(extra="forbid")

    name: str


class Material(BaseModel):
    """A PBR metallic-roughness material (scalars only)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    base_color: list[float]
    metallic: float = 1.0
    roughness: float = 1.0

    @field_validator("base_color")
    @classmethod
    def _base_color_is_rgba(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("base_color must be [r, g, b, a]")
        return value


class Primitive(BaseModel):
    """One triangle-mesh primitive: flat xyz positions + triangle indices."""

    model_config = ConfigDict(extra="forbid")

    positions: list[float] = Field(default_factory=list)
    indices: list[int] = Field(default_factory=list)
    material: str = ""

    @field_validator("positions")
    @classmethod
    def _positions_are_xyz_triples(cls, value: list[float]) -> list[float]:
        if len(value) % 3 != 0:
            raise ValueError("positions must be flat xyz triples")
        return value


class Mesh(BaseModel):
    """A named mesh, one or more primitives."""

    model_config = ConfigDict(extra="forbid")

    name: str
    primitives: list[Primitive] = Field(default_factory=list)


class Transform(BaseModel):
    """A node transform as translation / rotation (quaternion) / scale."""

    model_config = ConfigDict(extra="forbid")

    translation: list[float]
    rotation: list[float]
    scale: list[float]

    @field_validator("translation", "scale")
    @classmethod
    def _is_vec3(cls, value: list[float]) -> list[float]:
        if len(value) != 3:
            raise ValueError("translation/scale must be [x, y, z]")
        return value

    @field_validator("rotation")
    @classmethod
    def _is_quat(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("rotation must be a quaternion [x, y, z, w]")
        return value


class Object3D(BaseModel):
    """A scene object (glTF node): a transform and an optional mesh."""

    model_config = ConfigDict(extra="forbid")

    name: str
    transform: Transform
    mesh: str = ""
