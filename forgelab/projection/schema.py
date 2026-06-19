"""Human-readable description of what each projection level keeps and strips.

Lets an agent pick the right projection up front instead of probing by trial.
"""

from __future__ import annotations

from typing import Any

from forgelab.projection.projector import PROJECTION_LEVELS

_DOMAINS = ("hardware", "threed", "mechanical")

_LEVEL_SUMMARY = {
    "metadata": (
        "Document identity only: version, domain, meta, and node counts by type — no node data."
    ),
    "topology": (
        "Metadata plus a simplified node list: structure and references, no geometry coordinates."
    ),
    "geometry": (
        "Metadata plus full mesh/pad/sketch geometry; strips material definitions, scene "
        "hierarchy, and board constraints."
    ),
    "full": "The complete document — nothing stripped.",
}

# (includes, excludes) per domain per level.
_FIELDS: dict[str, dict[str, dict[str, list[str]]]] = {
    "hardware": {
        "metadata": {
            "includes": ["forgelab_version", "domain", "meta", "node_count", "nodes_by_type"],
            "excludes": ["all node props (components, nets, board)"],
        },
        "topology": {
            "includes": [
                "component reference/value/footprint/layer",
                "component pads as number + net name",
                "net code/name",
            ],
            "excludes": ["pad at/size/shape coordinates", "board constraints", "component uuid"],
        },
        "geometry": {
            "includes": ["component props incl. full pad at/size/shape", "net code/name"],
            "excludes": ["board constraints (design rules, layer stack, outline)"],
        },
        "full": {"includes": ["the entire document"], "excludes": []},
    },
    "threed": {
        "metadata": {
            "includes": ["forgelab_version", "domain", "meta", "node_count", "nodes_by_type"],
            "excludes": ["all node props (scenes, materials, meshes, objects)"],
        },
        "topology": {
            "includes": [
                "object name/mesh reference/transform",
                "mesh name",
                "material definitions",
            ],
            "excludes": ["mesh primitives (positions/indices)"],
        },
        "geometry": {
            "includes": ["mesh primitives (positions/indices)", "object transforms"],
            "excludes": ["material definitions", "scene hierarchy"],
        },
        "full": {"includes": ["the entire document"], "excludes": []},
    },
    "mechanical": {
        "metadata": {
            "includes": ["forgelab_version", "domain", "meta", "node_count", "nodes_by_type"],
            "excludes": ["all node props (parts, bodies, sketches, features)"],
        },
        "topology": {
            "includes": ["feature id/type", "the names of each feature's prop keys"],
            "excludes": ["sketch geometry/constraints values", "all prop values"],
        },
        "geometry": {
            "includes": ["full sketch geometry and constraints", "all parts/bodies/features"],
            "excludes": ["nothing domain-specific is stripped for mechanical geometry"],
        },
        "full": {"includes": ["the entire document"], "excludes": []},
    },
}


def projection_schema(domain: str, projection: str) -> dict[str, Any]:
    """Describe which fields a projection level includes/excludes for a domain."""
    if domain not in _DOMAINS:
        raise ValueError(f"unknown domain {domain!r}; valid: {', '.join(_DOMAINS)}")
    if projection not in PROJECTION_LEVELS:
        raise ValueError(
            f"unknown projection {projection!r}; valid: {', '.join(PROJECTION_LEVELS)}"
        )
    fields = _FIELDS[domain][projection]
    return {
        "domain": domain,
        "projection": projection,
        "description": _LEVEL_SUMMARY[projection],
        "includes": fields["includes"],
        "excludes": fields["excludes"],
        "levels": list(PROJECTION_LEVELS),
    }
