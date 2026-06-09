"""Tight per-domain JSON Schema for constraining LLM output.

``DOMAIN_VOCAB`` is the single source of truth mapping each domain's node
types to their Pydantic vocabulary model. Both this module (schema generation)
and ``forgelab.sdk.validation`` (deep validation) read from it, so they never
drift.
"""

from typing import Any

from pydantic import BaseModel

from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_MATERIAL,
    NODE_MESH,
    NODE_NET,
    NODE_OBJECT,
    NODE_SCENE,
    BoardConstraints,
    Component,
    Material,
    Mesh,
    Net,
    Object3D,
    Scene,
)

DOMAIN_VOCAB: dict[str, dict[str, type[BaseModel]]] = {
    "hardware": {
        NODE_BOARD: BoardConstraints,
        NODE_NET: Net,
        NODE_COMPONENT: Component,
    },
    "threed": {
        NODE_SCENE: Scene,
        NODE_MATERIAL: Material,
        NODE_MESH: Mesh,
        NODE_OBJECT: Object3D,
    },
}


def domain_schema(domain: str) -> dict[str, Any]:
    """Return a ForgeDocument-shaped JSON Schema specialized for ``domain``.

    ``domain`` is pinned to a const; ``nodes`` is a discriminated union on
    ``type`` where each variant's ``props`` is the real vocab model's schema.
    ``children`` references the same node union recursively (scene hierarchy).
    """
    try:
        vocab = DOMAIN_VOCAB[domain]
    except KeyError as exc:
        raise KeyError(f"Unknown domain {domain!r}; valid domains: {sorted(DOMAIN_VOCAB)}") from exc

    variants: list[dict[str, Any]] = []
    for node_type, model in vocab.items():
        variants.append(
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"const": node_type},
                    "props": model.model_json_schema(),
                    "children": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/node"},
                    },
                },
                "required": ["id", "type", "props"],
                "additionalProperties": False,
            }
        )

    return {
        "type": "object",
        "$defs": {"node": {"oneOf": variants}},
        "properties": {
            "forgelab_version": {"type": "string"},
            "domain": {"const": domain},
            "meta": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "generator": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                },
                "required": ["name"],
            },
            "nodes": {"type": "array", "items": {"$ref": "#/$defs/node"}},
        },
        "required": ["forgelab_version", "domain", "meta", "nodes"],
        "additionalProperties": False,
    }
