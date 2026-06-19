"""Geometry helpers: regular polygons and rotation quaternions.

Pure ``math``-only routines so an agent never has to derive vertex coordinates
or quaternion components by hand.
"""

from __future__ import annotations

import math


def calculate_polygon(sides: int, radius: float, center: list[float] | None = None) -> list[float]:
    """Vertices of a regular polygon as a flat ``[x, y, x, y, ...]`` list.

    Useful for tower/prism cross-sections, octagonal pads, and circular
    approximations (a many-sided polygon).

    Args:
        sides: number of sides (>= 3).
        radius: circumradius — distance from the centre to each vertex.
        center: ``[x, y]`` centre point; defaults to ``[0.0, 0.0]``.

    Returns:
        A flat list of ``2 * sides`` floats. The first vertex sits on the +X axis
        and vertices proceed counter-clockwise.
    """
    if sides < 3:
        raise ValueError("a polygon needs at least 3 sides")
    if radius <= 0:
        raise ValueError("radius must be > 0")
    cx, cy = (center[0], center[1]) if center is not None else (0.0, 0.0)
    coords: list[float] = []
    for i in range(sides):
        angle = 2.0 * math.pi * i / sides
        coords.append(round(cx + radius * math.cos(angle), 6))
        coords.append(round(cy + radius * math.sin(angle), 6))
    return coords


_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def calculate_rotation_matrix(angle_deg: float, axis: str = "y") -> list[float]:
    """Quaternion for a rotation about a principal axis, as ``[x, y, z, w]``.

    Despite the name, this returns a unit **quaternion** in the ``[x, y, z, w]``
    order that ForgeLab's threed transform rotation fields (and glTF) expect — so
    agents stop guessing quaternion components.

    Args:
        angle_deg: rotation angle in degrees (positive is counter-clockwise).
        axis: rotation axis, ``"x"``, ``"y"`` or ``"z"``. Defaults to ``"y"``,
            the up axis in the Y-up threed domain.

    Returns:
        A 4-element list ``[x, y, z, w]`` of a unit quaternion.
    """
    vec = _AXES.get(axis.lower())
    if vec is None:
        raise ValueError("axis must be 'x', 'y', or 'z'")
    half = math.radians(angle_deg) / 2.0
    s = math.sin(half)
    return [
        round(vec[0] * s, 6),
        round(vec[1] * s, 6),
        round(vec[2] * s, 6),
        round(math.cos(half), 6),
    ]
