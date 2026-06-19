"""Context projection: reduce a validated ForgeDocument to the fields a task needs.

``project`` returns a plain dict, not a ForgeDocument: a projected view may be
structurally incomplete (stripped nodes/fields), so it is deliberately not a
re-validatable document. The point is that the stripped data never leaves
ForgeLab — the agent only ever receives the projected dict.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from forgelab.spec import ForgeDocument
from forgelab.spec.models import Node

PROJECTION_LEVELS = ("metadata", "topology", "geometry", "full")

# Node types whose entire payload is stripped at the 'geometry' level, per domain:
# material definitions and scene hierarchy (threed), board constraints (hardware).
_GEOMETRY_STRIP = {
    "hardware": {"board"},
    "threed": {"material", "scene"},
    "mechanical": set[str](),
}


def project(document: ForgeDocument, level: str) -> dict[str, Any]:
    """Return ``document`` reduced to the given projection ``level`` as a plain dict."""
    if level not in PROJECTION_LEVELS:
        raise ValueError(f"unknown projection {level!r}; valid: {', '.join(PROJECTION_LEVELS)}")
    if level == "full":
        return document.model_dump(mode="json")
    result = _metadata(document)
    if level == "metadata":
        return result
    domain = document.domain.value
    if level == "topology":
        result["nodes"] = [_topology_node(node, domain) for node in document.walk()]
    else:  # geometry
        strip = _GEOMETRY_STRIP.get(domain, set())
        result["nodes"] = [
            {"id": node.id, "type": node.type, "props": node.props}
            for node in document.walk()
            if node.type not in strip
        ]
    return result


def _metadata(document: ForgeDocument) -> dict[str, Any]:
    counts: Counter[str] = Counter(node.type for node in document.walk())
    return {
        "forgelab_version": document.forgelab_version,
        "domain": document.domain.value,
        "meta": {
            "name": document.meta.name,
            "description": document.meta.description,
            "generator": document.meta.generator,
        },
        "node_count": sum(counts.values()),
        "nodes_by_type": dict(counts),
    }


def _topology_node(node: Node, domain: str) -> dict[str, Any]:
    if domain == "hardware":
        return _topology_hardware(node)
    if domain == "threed":
        return _topology_threed(node)
    if domain == "mechanical":
        # Features: id/type plus the names of their prop keys, no values (no geometry).
        return {"id": node.id, "type": node.type, "prop_keys": sorted(node.props)}
    return {"id": node.id, "type": node.type}


def _topology_hardware(node: Node) -> dict[str, Any]:
    props = node.props
    if node.type == "component":
        return {
            "id": node.id,
            "type": node.type,
            "props": {
                "reference": props.get("reference"),
                "value": props.get("value"),
                "footprint": props.get("footprint"),
                "layer": props.get("layer"),
                # Pads keep number + net name only — no at/size/shape coordinates.
                "pads": [
                    {"number": pad.get("number"), "net": pad.get("net", "")}
                    for pad in props.get("pads", [])
                ],
            },
        }
    if node.type == "net":
        return {
            "id": node.id,
            "type": node.type,
            "props": {"code": props.get("code"), "name": props.get("name")},
        }
    return {"id": node.id, "type": node.type}


def _topology_threed(node: Node) -> dict[str, Any]:
    props = node.props
    if node.type == "object":
        return {
            "id": node.id,
            "type": node.type,
            "props": {
                "name": props.get("name"),
                "mesh": props.get("mesh", ""),
                "transform": props.get("transform"),
            },
        }
    if node.type == "mesh":
        # Drop primitives (positions/indices) — keep the mesh name only.
        return {"id": node.id, "type": node.type, "props": {"name": props.get("name")}}
    if node.type == "material":
        return {"id": node.id, "type": node.type, "props": dict(props)}
    if node.type == "scene":
        return {"id": node.id, "type": node.type, "props": {"name": props.get("name")}}
    return {"id": node.id, "type": node.type}
