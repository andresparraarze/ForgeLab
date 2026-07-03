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
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_FILLET,
    NODE_LOFT,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SHELL,
    NODE_SKETCH,
    NODE_SWEEP,
    Body,
    Fillet,
    Loft,
    Pad,
    Part,
    Pocket,
    Shell,
    Sketch,
    Sweep,
)
from forgelab.spec.version import SPEC_VERSION

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
    "mechanical": {
        NODE_PART: Part,
        NODE_BODY: Body,
        NODE_SKETCH: Sketch,
        NODE_PAD: Pad,
        NODE_POCKET: Pocket,
        NODE_LOFT: Loft,
        NODE_SWEEP: Sweep,
        NODE_FILLET: Fillet,
        NODE_SHELL: Shell,
    },
}


def domain_schema(domain: str) -> dict[str, Any]:
    """Return a ForgeDocument-shaped JSON Schema specialized for ``domain``.

    ``domain`` is pinned to a const; ``nodes`` is a discriminated union on
    ``type`` where each variant's ``props`` is the real vocab model's schema.
    ``children`` references the same node union recursively (scene hierarchy).
    Each vocab model's own nested ``$defs`` (sub-models like ``Pad`` or
    ``Transform``) are hoisted to the top level so their ``#/$defs/...`` refs
    resolve against the returned document root.
    """
    try:
        vocab = DOMAIN_VOCAB[domain]
    except KeyError as exc:
        raise KeyError(f"Unknown domain {domain!r}; valid domains: {sorted(DOMAIN_VOCAB)}") from exc

    defs: dict[str, Any] = {"node": {"oneOf": []}}
    variants: list[dict[str, Any]] = defs["node"]["oneOf"]
    for node_type, model in vocab.items():
        props_schema = model.model_json_schema()
        for name, sub_schema in props_schema.pop("$defs", {}).items():
            defs[name] = sub_schema
        variants.append(
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"const": node_type},
                    "props": props_schema,
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
        "$defs": defs,
        "properties": {
            "forgelab_version": {"const": SPEC_VERSION},
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
