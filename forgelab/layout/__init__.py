"""Automatic layout algorithms (component placement, maze routing)."""

from forgelab.layout.placement import (
    DEFAULT_KEEPOUT,
    DEFAULT_LARGE_INSET,
    PlacementError,
    component_bbox,
    component_rotation,
    place_components,
    rotate_offset,
)
from forgelab.layout.routing import (
    DEFAULT_GRID_RESOLUTION,
    RoutingError,
    route_document,
)

__all__ = [
    "DEFAULT_KEEPOUT",
    "DEFAULT_LARGE_INSET",
    "DEFAULT_GRID_RESOLUTION",
    "PlacementError",
    "RoutingError",
    "component_bbox",
    "component_rotation",
    "place_components",
    "rotate_offset",
    "route_document",
]
