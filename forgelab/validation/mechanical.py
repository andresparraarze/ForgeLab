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

from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_FILLET,
    NODE_LOFT,
    NODE_PAD,
    NODE_POCKET,
    NODE_SHELL,
    NODE_SKETCH,
    NODE_SWEEP,
)

# Endpoints within this distance (mm) are treated as the same vertex.
_CLOSURE_TOL = 0.001

_FEATURE_TYPES = (
    NODE_SKETCH,
    NODE_PAD,
    NODE_POCKET,
    NODE_LOFT,
    NODE_SWEEP,
    NODE_FILLET,
    NODE_SHELL,
)


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

    # Sketch checks: circle radius positive (error) + line-loop closure (warn).
    for node in nodes:
        if node.type != NODE_SKETCH:
            continue
        is_sweep_path = node.id in sweep_path_refs or (
            str(node.props.get("name", "")) in sweep_path_refs
        )
        geometry = node.props.get("geometry") or []
        lines: list[list[float]] = []
        for geo in geometry:
            if not isinstance(geo, dict):
                continue
            if geo.get("geo_type") == "circle":
                if float(geo.get("radius", 0.0)) <= 0.0:
                    errors.append(f"sketch {node.id!r} has a circle with radius <= 0")
            elif geo.get("geo_type") == "line":
                points = geo.get("points") or []
                if len(points) == 4:
                    lines.append([float(p) for p in points])
        if lines and not is_sweep_path and not _lines_form_closed_loop(lines):
            warnings.append(
                f"sketch {node.id!r} line geometry is not a closed loop; "
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

    return errors, warnings


def _lines_form_closed_loop(lines: list[list[float]]) -> bool:
    """True if every line endpoint meets another line's start point.

    Each line is ``[x1, y1, x2, y2]``. A closed loop requires every end point to
    coincide (within ``_CLOSURE_TOL``) with the start point of some other line.
    """
    starts = [(line[0], line[1]) for line in lines]
    for i, line in enumerate(lines):
        end = (line[2], line[3])
        connected = any(j != i and _close(end, start) for j, start in enumerate(starts))
        if not connected:
            return False
    return True


def _close(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) <= _CLOSURE_TOL and abs(a[1] - b[1]) <= _CLOSURE_TOL
