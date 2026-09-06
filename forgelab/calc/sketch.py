"""Sketch profiles for mechanical parts, as ready-to-use IR geometry.

These build the three profiles a mechanical document needs constantly and that
are laborious and error-prone to write by hand: a bolt circle, a rounded
rectangle, and a slot. Each returns a list of ``SketchGeometry`` dicts that drop
straight into a sketch node's ``geometry``.

Why they earn their place. A rounded rectangle is four lines plus four corner
arcs, and every arc has to name a centre and a *start and end angle in degrees,
counter-clockwise from +X*, whose endpoints must land exactly on the ends of the
neighbouring lines or the profile does not close and nothing can be padded from
it. That is eight coupled pieces of trigonometry to get a shape a person would
describe in five words. An eight-hole bolt circle is eight ``cos``/``sin`` pairs
that all have to agree on the same radius. Arithmetic like that is precisely
what an LLM should not be doing inline, and the same reasoning already gave the
hardware domain ``calculate_pad_positions`` and ``calculate_polygon``.

Every profile these produce is closed by construction, so it passes the
closed-loop check in ``forgelab.validation.mechanical``.

Pure standard library with no forgelab imports at all: the output is plain dicts
matching the ``SketchGeometry`` field names.
"""

from __future__ import annotations

import math

# A sketch geometry primitive, in ``SketchGeometry`` field shape.
Geometry = dict[str, object]


def calculate_bolt_circle(
    count: int,
    radius: float,
    hole_radius: float,
    center: list[float] | None = None,
    start_angle: float = 0.0,
) -> list[Geometry]:
    """Circles evenly spaced around a bolt circle, as sketch geometry.

    The standard way holes are specified on a flange, a motor face or a lid.

    Args:
        count: number of holes (>= 1).
        radius: bolt-circle radius — centre of the pattern to centre of a hole.
        hole_radius: radius of each hole (half the drill diameter, not the
            diameter: an M3 clearance hole is 1.7, not 3.4).
        center: ``[x, y]`` centre of the pattern; defaults to the origin.
        start_angle: degrees counter-clockwise from +X for the first hole.

    Returns:
        ``count`` circle primitives, counter-clockwise from ``start_angle``.
    """
    if count < 1:
        raise ValueError("a bolt circle needs at least 1 hole")
    if radius <= 0:
        raise ValueError("bolt-circle radius must be > 0")
    if hole_radius <= 0:
        raise ValueError("hole_radius must be > 0 (it is a radius, not a diameter)")
    if hole_radius >= radius:
        raise ValueError(
            f"hole_radius {hole_radius} is not smaller than the bolt-circle radius "
            f"{radius}; the holes would swallow the pattern centre"
        )
    cx, cy = (center[0], center[1]) if center else (0.0, 0.0)
    step = 360.0 / count
    holes: list[Geometry] = []
    for i in range(count):
        angle = math.radians(start_angle + i * step)
        holes.append(
            {
                "geo_type": "circle",
                "center": [cx + radius * math.cos(angle), cy + radius * math.sin(angle)],
                "radius": hole_radius,
            }
        )
    return holes


def calculate_rounded_rect(
    width: float,
    height: float,
    corner_radius: float,
    origin: list[float] | None = None,
) -> list[Geometry]:
    """A closed rounded-rectangle profile: 4 lines + 4 corner arcs.

    The arcs are quarter turns whose endpoints meet the lines exactly, so the
    profile closes and can be padded or pocketed.

    Args:
        width: overall width along X (must exceed ``2 * corner_radius``).
        height: overall height along Y (same constraint).
        corner_radius: radius of each corner (> 0).
        origin: ``[x, y]`` of the lower-left corner of the bounding box;
            defaults to the origin.

    Returns:
        Eight primitives: bottom, right, top, left lines, then the four arcs
        counter-clockwise from the lower-right corner.
    """
    if corner_radius <= 0:
        raise ValueError("corner_radius must be > 0; use plain lines for a square corner")
    if width <= 2 * corner_radius or height <= 2 * corner_radius:
        raise ValueError(
            f"corner_radius {corner_radius} is too large for a {width}x{height} "
            f"rectangle; it must be under half the shorter side"
        )
    x0, y0 = (origin[0], origin[1]) if origin else (0.0, 0.0)
    x1, y1 = x0 + width, y0 + height
    r = corner_radius
    # Arc centres, inset from each corner by the radius.
    left, right = x0 + r, x1 - r
    bottom, top = y0 + r, y1 - r
    return [
        {"geo_type": "line", "points": [left, y0, right, y0]},  # bottom
        {"geo_type": "line", "points": [x1, bottom, x1, top]},  # right
        {"geo_type": "line", "points": [right, y1, left, y1]},  # top
        {"geo_type": "line", "points": [x0, top, x0, bottom]},  # left
        _arc([right, bottom], r, -90.0, 0.0),  # lower-right
        _arc([right, top], r, 0.0, 90.0),  # upper-right
        _arc([left, top], r, 90.0, 180.0),  # upper-left
        _arc([left, bottom], r, 180.0, 270.0),  # lower-left
    ]


def calculate_slot(x1: float, y1: float, x2: float, y2: float, width: float) -> list[Geometry]:
    """A closed slot profile: two parallel lines capped by two semicircles.

    The shape of an adjustment slot or a cable cut-out. ``(x1, y1)`` and
    ``(x2, y2)`` are the centres of the two end caps, so the slot's overall
    length is their distance plus ``width``.

    Args:
        x1, y1: centre of the first end cap.
        x2, y2: centre of the second end cap.
        width: full width of the slot; each cap has radius ``width / 2``.

    Returns:
        Four primitives: the two side lines and the two end arcs.
    """
    if width <= 0:
        raise ValueError("slot width must be > 0")
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError(
            "a slot needs two distinct end-cap centres; identical points describe "
            "a circle, so use a circle primitive instead"
        )
    r = width / 2.0
    # Unit normal to the slot axis: the sides sit +/- r along it.
    nx, ny = -dy / length, dx / length
    # The axis angle, so each cap sweeps counter-clockwise across its own half.
    axis = math.degrees(math.atan2(dy, dx))
    return [
        {
            "geo_type": "line",
            "points": [x1 + nx * r, y1 + ny * r, x2 + nx * r, y2 + ny * r],
        },
        {
            "geo_type": "line",
            "points": [x2 - nx * r, y2 - ny * r, x1 - nx * r, y1 - ny * r],
        },
        # Far cap sweeps from the +normal side round to the -normal side; the
        # near cap closes the loop on the other end.
        _arc([x2, y2], r, axis + 90.0, axis + 270.0),
        _arc([x1, y1], r, axis + 270.0, axis + 450.0),
    ]


def _arc(center: list[float], radius: float, start: float, end: float) -> Geometry:
    """An arc primitive with angles normalized into FreeCAD's 0-360 convention.

    Arcs always sweep counter-clockwise from ``start_angle`` to ``end_angle``,
    so the pair only has to be consistent, not minimal — but keeping them in
    ``[0, 360)`` matches what FreeCAD writes back on a round trip.
    """
    return {
        "geo_type": "arc",
        "center": [center[0], center[1]],
        "radius": radius,
        "start_angle": start % 360.0,
        "end_angle": end % 360.0,
    }
