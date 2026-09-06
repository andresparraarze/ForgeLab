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


class VerifyError(ValueError):
    """Raised when a document cannot be geometrically verified."""


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
    ``bbox`` and ``state``.

    ``volume`` is exact and ``bbox`` is the true extent (the kernel's cheap
    ``BoundBox`` over-reports on curved shapes, so the optimal one is used).

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
        elif not obj.get("valid", True):
            errors.append(f"{node.type} {node.id!r} built a shape OpenCASCADE reports as invalid")

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


def _union_bbox(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [min(b[i] for b in boxes) for i in range(3)] + [
        max(b[i] for b in boxes) for i in range(3, 6)
    ]
