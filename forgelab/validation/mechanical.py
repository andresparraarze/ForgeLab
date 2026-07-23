"""Constraint sanity checks for mechanical-domain documents.

These run after structural (Pydantic) validation as a pre-flight before FreeCAD:
they catch geometry and feature mistakes that otherwise surface as a silent
recompute failure when the ``.FCStd`` is opened. The checks return human-readable
``errors`` (fatal — the document should not be considered valid) and ``warnings``
(non-fatal — surfaced to the agent but not blocking).

Pure standard library. Node payloads are read as plain dicts (``Node.props``),
so a document that is structurally valid but geometrically nonsensical is still
inspectable here.
"""

from __future__ import annotations

import math

from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_FILLET,
    NODE_LOFT,
    NODE_PAD,
    NODE_POCKET,
    NODE_REVOLVE,
    NODE_SHELL,
    NODE_SKETCH,
    NODE_SWEEP,
)

# Endpoints within this distance (mm) are treated as the same vertex.
_CLOSURE_TOL = 0.001

# A 2D sketch-plane point.
_Point = tuple[float, float]

_FEATURE_TYPES = (
    NODE_SKETCH,
    NODE_PAD,
    NODE_POCKET,
    NODE_LOFT,
    NODE_SWEEP,
    NODE_FILLET,
    NODE_SHELL,
    NODE_REVOLVE,
)

# The revolution axis expressed in a sketch's local (x, y) plane, per
# (datum plane, global axis letter). None means the axis is perpendicular to
# the sketch plane — a profile revolved around its own normal is degenerate.
_AXIS_IN_PLANE: dict[tuple[str, str], tuple[float, float] | None] = {
    ("XY", "X"): (1.0, 0.0),
    ("XY", "Y"): (0.0, 1.0),
    ("XY", "Z"): None,
    ("XZ", "X"): (1.0, 0.0),
    ("XZ", "Z"): (0.0, 1.0),
    ("XZ", "Y"): None,
    ("YZ", "Y"): (1.0, 0.0),
    ("YZ", "Z"): (0.0, 1.0),
    ("YZ", "X"): None,
}

# Sketch plane spellings, matching the exporter's normalization.
_PLANE_KEYS = {
    "XY": "XY",
    "XY_PLANE": "XY",
    "TOP": "XY",
    "XZ": "XZ",
    "XZ_PLANE": "XZ",
    "FRONT": "XZ",
    "YZ": "YZ",
    "YZ_PLANE": "YZ",
    "RIGHT": "YZ",
}

# Points within this distance (mm) of the axis are "touching", which is fine
# (a solid of revolution commonly closes its profile along the axis).
_AXIS_TOL = 0.001


def check_mechanical(document: ForgeDocument) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a mechanical document.

    For non-mechanical documents the checks do not apply and two empty lists are
    returned, so callers can run this unconditionally.
    """
    if document.domain != Domain.MECHANICAL:
        return [], []

    nodes = list(document.walk())
    errors: list[str] = []
    warnings: list[str] = []

    body_ids = {n.id for n in nodes if n.type == NODE_BODY}
    name_to_id = {str(n.props.get("name", "")): n.id for n in nodes if n.type == NODE_BODY}
    name_to_id.pop("", None)
    only_body = next(iter(body_ids)) if len(body_ids) == 1 else None
    body_names = set(name_to_id)

    def resolve_body(ref: str) -> str | None:
        """Resolve a feature's body reference to a body node id, or None."""
        if ref in body_ids:
            return ref
        if ref in name_to_id:
            return name_to_id[ref]
        if not ref and only_body is not None:
            return only_body
        return None

    # Body reference consistency (error): a non-empty body link must resolve to
    # a real body, by node id or by the body's name.
    for node in nodes:
        if node.type not in _FEATURE_TYPES:
            continue
        ref = str(node.props.get("body", ""))
        if ref and ref not in body_ids and ref not in body_names:
            errors.append(
                f"{node.type} {node.id!r} references body {ref!r} "
                f"which is not a body in the document"
            )

    # Sketches referenced as a sweep path are deliberately open curves, so the
    # closed-loop warning below does not apply to them.
    sweep_path_refs = {str(n.props.get("path", "")) for n in nodes if n.type == NODE_SWEEP} - {""}

    # Sketch checks: circle/arc radius positive (error) + open-curve closure
    # (warn). Lines and arcs are both open segments, so they trace one profile
    # together — a rounded rectangle is 4 lines plus 4 corner arcs.
    for node in nodes:
        if node.type != NODE_SKETCH:
            continue
        is_sweep_path = node.id in sweep_path_refs or (
            str(node.props.get("name", "")) in sweep_path_refs
        )
        geometry = node.props.get("geometry") or []
        segments: list[tuple[_Point, _Point]] = []
        for geo in geometry:
            if not isinstance(geo, dict):
                continue
            geo_type = geo.get("geo_type")
            if geo_type in ("circle", "arc"):
                if float(geo.get("radius", 0.0)) <= 0.0:
                    errors.append(f"sketch {node.id!r} has a {geo_type} with radius <= 0")
                elif geo_type == "arc":
                    segments.append(_arc_endpoints(geo))
            elif geo_type == "line":
                points = geo.get("points") or []
                if len(points) == 4:
                    segments.append(
                        ((float(points[0]), float(points[1])), (float(points[2]), float(points[3])))
                    )
        if segments and not is_sweep_path and not _segments_form_closed_loop(segments):
            warnings.append(
                f"sketch {node.id!r} geometry is not a closed loop; "
                f"an open profile cannot be padded"
            )

    # Pad length positive (error): a pad with no positive length builds nothing,
    # unless it is a through-all pad.
    pad_height_by_body: dict[str | None, float] = {}
    for node in nodes:
        if node.type != NODE_PAD:
            continue
        length = float(node.props.get("length", 0.0))
        through_all = bool(node.props.get("through_all", False))
        if not through_all and length <= 0.0:
            errors.append(f"pad {node.id!r} has length <= 0 and is not through-all")
        owner = resolve_body(str(node.props.get("body", "")))
        pad_height_by_body[owner] = pad_height_by_body.get(owner, 0.0) + max(length, 0.0)

    # Pocket depth bounds (error): a pocket cannot cut deeper than the material
    # built by the pads in its body. Through-all pockets are exempt.
    for node in nodes:
        if node.type != NODE_POCKET:
            continue
        if bool(node.props.get("through_all", False)):
            continue
        length = float(node.props.get("length", 0.0))
        owner = resolve_body(str(node.props.get("body", "")))
        available = pad_height_by_body.get(owner, 0.0)
        if length > available:
            errors.append(
                f"pocket {node.id!r} length {length} exceeds the available "
                f"material {available} in its body"
            )

    # Part-workbench feature checks: cross-references must resolve (like the
    # body-reference check above, ids or display names both count) and the
    # scalar parameters must be geometrically meaningful.
    node_ids = {n.id for n in nodes}
    node_names = {str(n.props.get("name", "")) for n in nodes} - {""}

    def unresolved(ref: str) -> bool:
        return ref not in node_ids and ref not in node_names

    for node in nodes:
        if node.type == NODE_LOFT:
            profiles = node.props.get("profiles") or []
            if len(profiles) < 2:
                errors.append(
                    f"loft {node.id!r} has {len(profiles)} profile(s); a loft needs at least 2"
                )
            for ref in profiles:
                if unresolved(str(ref)):
                    errors.append(
                        f"loft {node.id!r} references profile {ref!r} "
                        f"which does not exist in the document"
                    )
        elif node.type == NODE_SWEEP:
            for role in ("profile", "path"):
                ref = str(node.props.get(role, ""))
                if unresolved(ref):
                    errors.append(
                        f"sweep {node.id!r} references {role} {ref!r} "
                        f"which does not exist in the document"
                    )
        elif node.type == NODE_FILLET:
            if float(node.props.get("radius", 0.0)) <= 0.0:
                errors.append(f"fillet {node.id!r} has radius <= 0")
            ref = str(node.props.get("target", ""))
            if unresolved(ref):
                errors.append(
                    f"fillet {node.id!r} references target {ref!r} "
                    f"which does not exist in the document"
                )
        elif node.type == NODE_SHELL:
            if float(node.props.get("thickness", 0.0)) <= 0.0:
                errors.append(f"shell {node.id!r} has thickness <= 0")
            ref = str(node.props.get("target", ""))
            if unresolved(ref):
                errors.append(
                    f"shell {node.id!r} references target {ref!r} "
                    f"which does not exist in the document"
                )
        elif node.type == NODE_REVOLVE:
            angle = float(node.props.get("angle", 360.0))
            if angle <= 0.0 or angle > 360.0:
                errors.append(
                    f"revolve {node.id!r} has angle {angle:g}; it must be > 0 and <= 360 degrees"
                )
            ref = str(node.props.get("profile", ""))
            if unresolved(ref):
                errors.append(
                    f"revolve {node.id!r} references profile {ref!r} "
                    f"which does not exist in the document"
                )
            else:
                error = _revolve_axis_error(node.id, node.props, nodes)
                if error:
                    errors.append(error)

    return errors, warnings


def _revolve_axis_error(revolve_id: str, props: dict, nodes: list) -> str | None:
    """An error message when a revolve profile crosses (or is normal to) its axis.

    A profile with geometry on both sides of the revolution axis produces
    self-intersecting geometry in FreeCAD, so every profile point must sit on
    one side of the axis (touching it is allowed) within the sketch's local
    plane. The axis is taken through the sketch-local origin, matching the
    exporter's Base of (0, 0, 0).
    """
    ref = str(props.get("profile", ""))
    sketch = next(
        (
            n
            for n in nodes
            if n.type == NODE_SKETCH and (n.id == ref or str(n.props.get("name", "")) == ref)
        ),
        None,
    )
    if sketch is None:
        return None  # not a sketch: the exporter reports that separately
    axis = str(props.get("axis", "Z")).strip().upper()
    plane = _PLANE_KEYS.get(str(sketch.props.get("plane", "XY")).strip().upper(), "XY")
    direction = _AXIS_IN_PLANE.get((plane, axis))
    if direction is None:
        return (
            f"revolve {revolve_id!r} axis {axis} is perpendicular to profile "
            f"{ref!r}'s sketch plane ({plane}); the profile must be sketched on "
            f"a plane containing the revolution axis"
        )
    dx, dy = direction
    sides = set()
    for geo in sketch.props.get("geometry") or []:
        if not isinstance(geo, dict):
            continue
        points: list[tuple[float, float]] = []
        if geo.get("geo_type") == "line" and len(geo.get("points") or []) == 4:
            x1, y1, x2, y2 = (float(v) for v in geo["points"])
            points = [(x1, y1), (x2, y2)]
        elif geo.get("geo_type") == "circle" and len(geo.get("center") or []) == 2:
            cx, cy = (float(v) for v in geo["center"])
            r = float(geo.get("radius", 0.0))
            # The circle's extreme points perpendicular to the axis.
            points = [(cx - dy * r, cy + dx * r), (cx + dy * r, cy - dx * r)]
        for px, py in points:
            signed = dx * py - dy * px  # signed side of the axis line
            if signed > _AXIS_TOL:
                sides.add(1)
            elif signed < -_AXIS_TOL:
                sides.add(-1)
    if len(sides) == 2:
        return (
            f"revolve {revolve_id!r} profile {ref!r} crosses the revolution axis "
            f"{axis}; all profile geometry must stay on one side of the axis "
            f"(touching it is allowed)"
        )
    return None


def _arc_endpoints(geo: dict[str, object]) -> tuple[_Point, _Point]:
    """The two points where an arc meets its neighbours in a profile.

    Angles are degrees counter-clockwise from +X, matching FreeCAD's Sketcher
    convention (see ``SketchGeometry``).
    """
    center = geo.get("center") or [0.0, 0.0]
    cx, cy = float(center[0]), float(center[1])  # type: ignore[index]
    radius = float(geo.get("radius", 0.0))  # type: ignore[arg-type]
    a0 = math.radians(float(geo.get("start_angle", 0.0)))  # type: ignore[arg-type]
    a1 = math.radians(float(geo.get("end_angle", 0.0)))  # type: ignore[arg-type]
    return (
        (cx + radius * math.cos(a0), cy + radius * math.sin(a0)),
        (cx + radius * math.cos(a1), cy + radius * math.sin(a1)),
    )


def _segments_form_closed_loop(segments: list[tuple[_Point, _Point]]) -> bool:
    """True if every open-curve endpoint in the profile meets exactly one other.

    Lines and arcs are both open segments; a closed profile is one where the
    endpoints pair up, so each distinct vertex (within ``_CLOSURE_TOL``) is
    touched by exactly two segment ends. Several disjoint loops in one sketch
    still pass — that is a legal profile with an island, e.g. a plate outline
    plus a square cut-out.

    The pairing is deliberately *undirected*. A FreeCAD arc always sweeps
    counter-clockwise, so in a clockwise-traced profile an arc's ``start`` is
    the point the traversal *leaves* by; requiring end-meets-start would reject
    a perfectly closed outline for the direction its arcs are obliged to have.
    """
    vertices: list[_Point] = []
    degree: list[int] = []
    for segment in segments:
        for point in segment:
            for i, known in enumerate(vertices):
                if _close(point, known):
                    degree[i] += 1
                    break
            else:
                vertices.append(point)
                degree.append(1)
    return all(count == 2 for count in degree)


def _close(a: _Point, b: _Point) -> bool:
    return abs(a[0] - b[0]) <= _CLOSURE_TOL and abs(a[1] - b[1]) <= _CLOSURE_TOL
