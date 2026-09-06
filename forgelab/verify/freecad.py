"""Verify a mechanical document by building it in the real FreeCAD kernel.

``forgelab.validation.mechanical`` answers "is this description sane?" from the
parametric text alone — closed profiles, positive radii, bounding boxes that
overlap. It says so itself: its empty-cut check "is not a geometric
intersection test". This module answers the question only OpenCASCADE can:
**did the part actually get built?**

That gap is not academic. FreeCAD reports no error for geometry that produces
nothing — a boolean whose operands miss each other, a fillet radius larger than
the face it rounds, a shell that collapses inward — all recompute to a valid,
"Up-to-date" object holding zero solids and volume 0. Such a document passes
every existing check, exports cleanly, and opens as an empty part.

Verification therefore exports the document, opens it in ``freecadcmd``,
recomputes, and reports per IR node what the kernel built: solids, volume,
validity, recompute state. A node that should be solid and is not is an error,
named by its own node id rather than by a FreeCAD object name.

Building something is not the same as building the right thing, so a second
class of check asks whether each feature actually *did* anything: a pocket that
cut nothing (the wrong-way sketch, by far the commonest mistake), a shell that
hollowed nothing, a fillet that rounded no edges, and an all-edges fillet whose
analytically-derived edge count disagrees with the kernel's. Every one of those
produces a valid solid that passes every other check the project has.

Requires FreeCAD (see :func:`available`); it is an optional dependency, so
callers should check first or handle :class:`VerifyError`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from forgelab.exporters.mechanical.freecad import FreeCADExporter
from forgelab.exporters.mechanical.realxml import fc_name
from forgelab.formats import freecad_kernel
from forgelab.spec import Domain, ForgeDocument
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_BOOLEAN,
    NODE_FILLET,
    NODE_LOFT,
    NODE_PAD,
    NODE_POCKET,
    NODE_REVOLVE,
    NODE_SHELL,
    NODE_SWEEP,
)

#: Node types whose FreeCAD object must end up as a real solid. ``part`` is a
#: container (its shape is a compound of its children) and ``sketch`` is a wire,
#: so neither is expected to have volume and neither is checked.
_SOLID_NODES = (
    NODE_BODY,
    NODE_PAD,
    NODE_POCKET,
    NODE_LOFT,
    NODE_SWEEP,
    NODE_REVOLVE,
    NODE_FILLET,
    NODE_SHELL,
    NODE_BOOLEAN,
)

#: Volume (mm³) at or below which a shape is treated as having built nothing.
_ZERO_VOLUME = 1e-9

#: Relative volume change below which a feature is treated as having changed
#: nothing. Both volumes come from the same kernel in the same run, so a genuine
#: no-op is bit-identical and this only has to survive float noise.
_UNCHANGED = 1e-9

#: Node types that must alter the solid they are applied to. A fillet rounds
#: edges, a shell hollows, a pocket cuts; any of them leaving the previous
#: solid's volume *and* face count untouched means it did nothing, which FreeCAD
#: does not report. The fillet and shell are applied to an explicit ``target``;
#: a pocket is applied to whatever came before it in its body's chain.
_MUST_CHANGE = (NODE_FILLET, NODE_SHELL, NODE_POCKET)

#: Feature types that form a body's ordered pad/pocket chain, each built on the
#: result of the one before it.
_CHAIN_FEATURES = (NODE_PAD, NODE_POCKET)


class VerifyError(ValueError):
    """Raised when a document cannot be geometrically verified."""


def _target_resolver(document: ForgeDocument):
    """Map a feature's ``target`` reference to a node id.

    A reference may name a node by id or by its display ``name``, the same two
    forms the exporter accepts.
    """
    ids = {node.id for node in document.walk()}
    by_label: dict[str, str] = {}
    for node in document.walk():
        label = node.props.get("name")
        if isinstance(label, str) and label not in ids:
            by_label.setdefault(label, node.id)

    def resolve(ref: str) -> str | None:
        if ref in ids:
            return ref
        return by_label.get(ref)

    return resolve


def available() -> bool:
    """True when the FreeCAD kernel can be driven (``freecadcmd`` on PATH)."""
    return freecad_kernel.available()


def verify_document(document: ForgeDocument, timeout: int | None = None) -> dict[str, Any]:
    """Build ``document`` in FreeCAD and report what the kernel produced.

    Returns::

        {
          "verified": bool,          # no errors
          "errors": [str],           # geometry that failed to build
          "warnings": [str],         # suspicious but not fatal
          "solid_count": int,        # finished solids in the part
          "total_volume": float,     # mm^3, summed over the finished solids
          "bbox": [xmin, ymin, zmin, xmax, ymax, zmax] | None,
          "nodes": [ {...per-node report...} ],
        }

    Each node report carries ``node_id``, ``type``, ``freecad_name``, ``final``
    (whether it is one of the part's finished solids) and — when the object has
    a shape — ``valid``, ``null``, ``volume``, ``area``, ``solids``, ``faces``,
    ``edges``, ``bbox`` and ``state``.

    ``volume`` is exact and ``bbox`` is the true extent (the kernel's cheap
    ``BoundBox`` over-reports on curved shapes, so the optimal one is used).
    ``edges`` is the count an all-edges fillet needs and the exporter can only
    estimate; read it here when a fillet asks for an explicit ``edges`` list.

    Errors cover both halves of "did this work": geometry that failed to build
    or built nothing, and features that built a valid solid without doing what
    they describe — a pocket that cut nothing, a shell that hollowed nothing, an
    all-edges fillet whose derived edge count disagrees with the kernel.

    Raises :class:`VerifyError` for a non-mechanical document, and
    ``FreeCADKernelError`` when FreeCAD is not installed or the build fails.
    """
    if document.domain != Domain.MECHANICAL:
        raise VerifyError("geometry verification applies to mechanical documents only")

    build = FreeCADExporter().build(document)
    kwargs = {} if timeout is None else {"timeout": timeout}
    with tempfile.TemporaryDirectory(prefix="forgelab-verify-") as tmp:
        target = Path(tmp) / f"{document.meta.name or 'part'}.FCStd"
        target.write_bytes(build.data)
        objects = freecad_kernel.inspect_document(target, **kwargs)

    by_fc_name = {obj["name"]: obj for obj in objects}
    final = set(build.solid_names)
    # A body only has to build something when it owns a pad/pocket chain. One
    # holding only Part-workbench features (a loft, a revolve — top-level
    # objects that never become a tip) has a null shape by design; the finished
    # solid is the loft or revolve itself. Reading that as "built nothing" would
    # fail organic_grip and rounded_knob, both of which are perfectly good parts.
    solid_bodies = set(build.solid_body_names)

    resolve_target = _target_resolver(document)
    predecessor_of = _chain_predecessors(document, resolve_target)

    errors: list[str] = []
    warnings: list[str] = []
    reports: list[dict[str, Any]] = []

    for node in document.walk():
        name = fc_name(node.id)
        obj = by_fc_name.get(name)
        if obj is None:
            # Every exported node becomes an object, so a miss means the export
            # and the kernel disagree — worth surfacing rather than skipping.
            warnings.append(
                f"{node.type} {node.id!r} has no object named {name!r} in the built document"
            )
            continue
        report: dict[str, Any] = {
            "node_id": node.id,
            "type": node.type,
            "freecad_name": name,
            "final": name in final,
        }
        report.update({k: v for k, v in obj.items() if k not in ("name", "label", "type_id")})
        reports.append(report)

        # One failure, one error. A feature that fails to recompute also has no
        # volume, and reporting both facts about it reads as two defects.
        state = obj.get("state") or []
        if any("Invalid" in s or "Error" in s for s in state):
            errors.append(f"{node.type} {node.id!r} failed to recompute in FreeCAD (state {state})")
            continue
        if "Touched" in state:
            warnings.append(
                f"{node.type} {node.id!r} was still marked Touched after recompute, "
                f"so FreeCAD may not have rebuilt it"
            )

        if node.type not in _SOLID_NODES or not obj.get("has_shape"):
            continue
        if node.type == NODE_BODY and name not in solid_bodies:
            continue
        if obj.get("null") or obj.get("solids", 0) == 0 or obj.get("volume", 0.0) <= _ZERO_VOLUME:
            errors.append(
                f"{node.type} {node.id!r} built no solid geometry (volume "
                f"{obj.get('volume', 0.0):g}, {obj.get('solids', 0)} solids) — FreeCAD "
                f"reports no error for this, but the feature produced nothing"
            )
            continue
        if not obj.get("valid", True):
            errors.append(f"{node.type} {node.id!r} built a shape OpenCASCADE reports as invalid")
            continue

        if node.type in _MUST_CHANGE:
            if node.type == NODE_POCKET:
                target = _chain_object(predecessor_of.get(node.id), by_fc_name)
            else:
                target = _target_object(node, by_fc_name, resolve_target)
            no_op = _describe_no_op(node, obj, target)
            if no_op is not None:
                errors.append(no_op)
                continue
            if node.type == NODE_FILLET and node.id in build.estimated_fillet_edges:
                miscount = _describe_edge_miscount(
                    node, target, build.estimated_fillet_edges[node.id]
                )
                if miscount is not None:
                    errors.append(miscount)

    finals = [by_fc_name[n] for n in build.solid_names if n in by_fc_name]
    if not finals:
        errors.append("the document produced no finished solid; there is nothing to export")
    elif len(finals) > 1:
        # Not an error — a document may legitimately describe several parts —
        # but for a document meant to be ONE part this is the signature of a
        # feature built on the wrong predecessor, and the result is two solids
        # overlapping in space rather than one. Seen for real: a fillet whose
        # target was the pad rather than the last pocket left the fully-pocketed
        # body and a fillet of the raw pad as separate finished solids, with the
        # holes present in one and absent in the other.
        names = ", ".join(repr(n) for n in build.solid_names)
        warnings.append(
            f"the document produced {len(finals)} separate finished solids ({names}); "
            f"if this is meant to be one part, a feature is probably built on the "
            f"wrong predecessor — check that each fillet/shell/boolean targets the "
            f"last feature in the chain, not an earlier one"
        )

    return {
        "verified": not errors,
        "errors": errors,
        "warnings": warnings,
        "solid_count": sum(int(f.get("solids", 0)) for f in finals),
        "total_volume": sum(float(f.get("volume", 0.0)) for f in finals),
        "bbox": _union_bbox([f["bbox"] for f in finals if f.get("bbox")]),
        "nodes": reports,
    }


def _chain_predecessors(document: ForgeDocument, resolve) -> dict[str, str]:
    """Map each pad/pocket to the feature before it in its own body's chain.

    A pocket has no ``target``: it cuts whatever its body has built so far, in
    document order, which is the same order the exporter writes the chain in.
    """
    tip: dict[str, str] = {}
    previous: dict[str, str] = {}
    for node in document.walk():
        if node.type not in _CHAIN_FEATURES:
            continue
        ref = node.props.get("body")
        body_id = resolve(ref) if isinstance(ref, str) and ref else None
        if body_id is None:
            continue
        if body_id in tip:
            previous[node.id] = tip[body_id]
        tip[body_id] = node.id
    return previous


def _chain_object(node_id: str | None, by_fc_name) -> dict[str, Any] | None:
    """The kernel's report for a chain predecessor, if it built anything."""
    if node_id is None:
        return None
    obj = by_fc_name.get(fc_name(node_id))
    if obj is None or obj.get("null") or not obj.get("has_shape"):
        return None
    return {**obj, "node_id": node_id}


def _target_object(node, by_fc_name, resolve_target) -> dict[str, Any] | None:
    """The kernel's report for the feature this node is applied to, if any."""
    ref = node.props.get("target")
    if not isinstance(ref, str) or not ref:
        return None
    target_id = resolve_target(ref)
    if target_id is None:
        return None
    target = by_fc_name.get(fc_name(target_id))
    if target is None or target.get("null") or not target.get("has_shape"):
        return None
    return {**target, "node_id": target_id}


def _describe_edge_miscount(node, target, estimated: int) -> str | None:
    """Report an all-edges fillet that did not round every edge after all.

    This is the check the estimator has never had. A fillet with no explicit
    ``edges`` means "round everything", but the exporter writes out concrete
    1-based edge ids and has no OCC kernel to enumerate them, so it derives the
    count from the sketch — ``realxml._estimate_edge_count``, formulas pinned
    experimentally against FreeCAD 1.1, and ``None`` (a hard export error) for
    the shapes it cannot reason about.

    Guess too high and FreeCAD refuses: the object comes back Invalid and the
    recompute check above catches it. Guess too **low** and nothing anywhere
    complains. The part builds, the volume is plausible, the render looks right,
    and some edges are simply left sharp — which is the one outcome a person
    asking for "round all the edges" would notice immediately and no check
    would. Only the kernel knows the real count; now that verification runs
    there, it can say so.
    """
    if target is None:
        return None
    actual = target.get("edges")
    if not isinstance(actual, int) or actual == estimated:
        return None
    return (
        f"fillet {node.id!r} asks to round every edge of {target['node_id']!r}, and the "
        f"exporter derived {estimated} edge{'' if estimated == 1 else 's'} for it — but "
        f"the kernel reports {actual}. "
        + (
            f"{actual - estimated} edge{'' if actual - estimated == 1 else 's'} were left "
            f"sharp. Pass an explicit 'edges' list of 1..{actual} to round all of them"
            if actual > estimated
            else f"The extra ids do not exist; pass an explicit 'edges' list of 1..{actual}"
        )
    )


def _describe_no_op(node, obj, target) -> str | None:
    """Report a feature that built a solid identical to the one it was given.

    The failure this exists for is quiet. An all-edges fillet has no OCC kernel
    at export time, so the exporter derives the edge ids analytically from the
    sketch (``realxml._estimate_edge_count``, formulas pinned experimentally
    against FreeCAD 1.1). Guess too *high* and FreeCAD says so — the object comes
    back Invalid and the state check above catches it. Guess too *low* and
    nothing complains anywhere: the part builds, the volume is plausible, the
    render looks like a part, and some edges are simply not rounded. Guess zero
    and the feature is a no-op that every existing check calls a success.

    A pocket fails the same way and more often: a sketch on the XY plane cuts
    downward, so a pocket over a pad rising from z=0 removes nothing unless
    ``reversed`` is true. The part still builds, exports and renders — without
    the hole.

    Volume and face count are both required to be unchanged before this fires.
    Either alone would be a heuristic: a fillet rounding one small edge of a
    large part moves the volume very little, and a shell can leave the face
    count alone. Both untouched, from the same kernel in the same run, means the
    feature did nothing at all.
    """
    if target is None:
        return None
    target_id = target["node_id"]

    before, after = float(target.get("volume", 0.0)), float(obj.get("volume", 0.0))
    if before <= _ZERO_VOLUME:
        return None
    if abs(after - before) / before > _UNCHANGED:
        return None
    if obj.get("faces") != target.get("faces"):
        return None

    if node.type == NODE_POCKET:
        return (
            f"pocket {node.id!r} cut nothing: the solid is identical to {target_id!r} "
            f"before it (volume {after:g}, {obj.get('faces')} faces, both unchanged). "
            f"The profile most likely misses the material — a sketch on the XY plane "
            f"cuts downward unless 'reversed' is true, and a blind pocket needs a "
            f"'length' that reaches. FreeCAD reports no error for a cut that removes "
            f"nothing"
        )
    if node.type == NODE_SHELL:
        return (
            f"shell {node.id!r} produced the same solid as its target {target_id!r} "
            f"(volume {after:g}, {obj.get('faces')} faces, both unchanged) — it hollowed "
            f"nothing. Check 'thickness' and 'faces_to_remove'; FreeCAD cannot hollow a "
            f"solid with no opening and reports no error when it fails to"
        )
    return (
        f"fillet {node.id!r} produced the same solid as its target {target_id!r} "
        f"(volume {after:g}, {obj.get('faces')} faces, both unchanged) — it rounded no "
        f"edges. Pass an explicit 'edges' list (1-based OCC edge indices on the "
        f"target's shape) rather than relying on the all-edges default"
    )


def _union_bbox(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [min(b[i] for b in boxes) for i in range(3)] + [
        max(b[i] for b in boxes) for i in range(3, 6)
    ]
