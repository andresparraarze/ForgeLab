"""Typed 3D / game vocabulary for the ForgeLab IR.

These models describe glTF-style scene concepts — materials, meshes, geometry
primitives, transforms, and scene objects. Like the hardware vocabulary they are
not a new document root: they serialize into the generic ``Node`` graph. Scene
hierarchy is expressed with ``Node.children`` (objects nest inside objects);
meshes and materials are flat, id-referenced top-level nodes.

Coordinate convention: the threed domain is **Y-up**, matching glTF's native
axis convention. Author geometry with the Y axis as up (an object's height goes
on the Y component), never Z. The glTF exporter passes coordinates straight
through, and Blender's glTF importer converts Y-up back to its own Z-up world,
so Y-up authoring imports upright; a Z-up document would be double-converted and
land tipped on its side.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NODE_SCENE = "scene"
NODE_OBJECT = "object"
NODE_MESH = "mesh"
NODE_MATERIAL = "material"


class Scene(BaseModel):
    """A glTF scene: a named container for the object graph."""

    model_config = ConfigDict(extra="forbid")

    name: str


class Material(BaseModel):
    """A PBR metallic-roughness material.

    ``base_color`` is RGBA; an alpha below 1.0 marks the material as
    translucent, and the glTF exporter emits ``alphaMode: "BLEND"`` for it so
    viewers actually blend it (glTF defaults to OPAQUE and ignores the alpha
    channel otherwise).

    ``base_color_texture`` is an optional path to an image file — the surface
    detail (wood grain, brushed metal, woven fabric) that a flat RGBA cannot
    express. It is resolved relative to the document's directory, the same way
    an OBJ's companion ``.mtl`` is. The mesh primitives that use a textured
    material MUST carry ``uvs``; without them there is nothing to map the image
    onto, and ``check_threed`` reports it as an error.

    Texture and colour **multiply**, they do not replace each other. That is
    glTF's rule verbatim — ``baseColorFactor`` is defined as a "linear
    multiplier for the sampled texels of the base color texture" — so a white
    ``base_color`` (the usual choice with a texture) shows the image unchanged,
    and a coloured one tints it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    base_color: list[float]
    metallic: float = 1.0
    roughness: float = 1.0
    base_color_texture: str = Field(
        default="",
        description=(
            "Optional path to a base-colour image, relative to the document's "
            "directory (e.g. 'textures/wood.png'). Requires uvs on every "
            "primitive that uses this material."
        ),
    )

    @field_validator("base_color")
    @classmethod
    def _base_color_is_rgba(cls, value: list[float]) -> list[float]:
        # [r, g, b] is accepted as shorthand for [r, g, b, 1.0]: fully opaque
        # (mirrors Component.at accepting [x, y] for [x, y, 0]).
        if len(value) == 3:
            return [value[0], value[1], value[2], 1.0]
        if len(value) != 4:
            raise ValueError("base_color must be [r, g, b, a] (or [r, g, b] for opaque)")
        return value


class Primitive(BaseModel):
    """One triangle-mesh primitive: flat xyz positions + triangle indices.

    ``uvs`` are optional texture coordinates — flat ``[u, v]`` pairs, one pair
    per position, packed the same way positions are. They are what maps a 2D
    image onto the surface; without them a textured material has nowhere to
    put its image. Omitting ``uvs`` is the default and changes nothing.

    UV convention is glTF's: origin at the **top-left**, V increasing
    downwards. (Blender's is bottom-left, so the ``blender_script`` exporter
    flips V — exactly what Blender's own glTF importer does.)
    """

    model_config = ConfigDict(extra="forbid")

    positions: list[float] = Field(default_factory=list)
    indices: list[int] = Field(default_factory=list)
    uvs: list[float] = Field(
        default_factory=list,
        description=(
            "Optional flat [u, v] texture coordinates, one pair per position "
            "(so len(uvs) // 2 == len(positions) // 3)."
        ),
    )
    material: str = Field(
        default="",
        description=(
            "Node id of the material to apply — the referenced material node's "
            "top-level 'id' field, e.g. 'mat_red'. Do NOT use the material's "
            "display name (its props.name, e.g. 'vermilion')."
        ),
    )

    @field_validator("positions")
    @classmethod
    def _positions_are_xyz_triples(cls, value: list[float]) -> list[float]:
        if len(value) % 3 != 0:
            raise ValueError("positions must be flat xyz triples")
        return value

    @field_validator("uvs")
    @classmethod
    def _uvs_are_uv_pairs(cls, value: list[float]) -> list[float]:
        if len(value) % 2 != 0:
            raise ValueError("uvs must be flat [u, v] pairs")
        return value

    @model_validator(mode="after")
    def _uvs_match_positions(self) -> Primitive:
        if self.uvs and len(self.uvs) // 2 != len(self.positions) // 3:
            raise ValueError(
                f"uvs must have one [u, v] pair per position: "
                f"{len(self.uvs) // 2} pairs for {len(self.positions) // 3} positions"
            )
        return self


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


_MODIFIER_TYPES = ("subsurf", "bevel", "boolean", "solidify")
_BOOLEAN_OPERATIONS = ("difference", "union", "intersect")


class Modifier(BaseModel):
    """One entry in an object's Blender modifier stack.

    Modifiers describe procedural geometry (smoothing, rounded edges, cuts,
    wall thickness) that Blender's own modifier evaluation computes when the
    exported script runs — the IR carries only the description. Each type
    reads its own fields; the others are ignored:

    - ``subsurf``: ``levels`` (viewport, default 2), ``render_levels``
      (defaults to ``levels`` when omitted).
    - ``bevel``: ``width`` (default 0.02), ``segments`` (default 3),
      ``limit_method`` ('angle', 'none', 'weight' or 'vgroup'; default
      'angle').
    - ``boolean``: ``operation`` ('difference', 'union' or 'intersect') and
      ``target`` (the node id of the object supplying the cutting/joining
      volume; it is hidden from render since the boolean consumes it).
    - ``solidify``: ``thickness`` (default 0.02).
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    levels: int = 2
    render_levels: int | None = None
    width: float = 0.02
    segments: int = 3
    limit_method: str = "angle"
    operation: str = "difference"
    target: str = ""
    thickness: float = 0.02

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in _MODIFIER_TYPES:
            raise ValueError(f"modifier type must be one of {_MODIFIER_TYPES}")
        return value

    @field_validator("limit_method")
    @classmethod
    def _known_limit_method(cls, value: str) -> str:
        if value.lower() not in ("angle", "none", "weight", "vgroup"):
            raise ValueError("limit_method must be 'angle', 'none', 'weight' or 'vgroup'")
        return value.lower()

    @field_validator("operation")
    @classmethod
    def _known_operation(cls, value: str) -> str:
        if value.lower() not in _BOOLEAN_OPERATIONS:
            raise ValueError(f"boolean operation must be one of {_BOOLEAN_OPERATIONS}")
        return value.lower()

    @model_validator(mode="after")
    def _boolean_needs_target(self) -> Modifier:
        if self.type == "boolean" and not self.target:
            raise ValueError("a boolean modifier needs a 'target' object node id")
        return self


class Object3D(BaseModel):
    """A scene object (glTF node): a transform and an optional mesh."""

    model_config = ConfigDict(extra="forbid")

    name: str
    transform: Transform
    mesh: str = Field(
        default="",
        description=(
            "Node id of the mesh to attach — the referenced mesh node's "
            "top-level 'id' field, e.g. 'mesh_cube'. Do NOT use the mesh's "
            "display name (its props.name)."
        ),
    )
    modifiers: list[Modifier] = Field(
        default_factory=list,
        description=(
            "Ordered Blender modifier stack applied to this object's mesh, "
            "first to last — exactly Blender's own stack order. Only honoured "
            "by the Blender script exporter; glTF export bakes nothing and "
            "ignores it."
        ),
    )
