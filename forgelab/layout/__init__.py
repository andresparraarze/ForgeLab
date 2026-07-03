"""Automatic layout algorithms (component placement)."""

from forgelab.layout.placement import (
    DEFAULT_KEEPOUT,
    PlacementError,
    component_bbox,
    place_components,
)

__all__ = [
    "DEFAULT_KEEPOUT",
    "PlacementError",
    "component_bbox",
    "place_components",
]
