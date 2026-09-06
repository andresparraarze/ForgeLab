"""Headless FreeCAD as a geometry oracle: recompute, tessellate, convert.

Everything else in ``forgelab.formats`` reads and writes bytes. This module is
different in kind: it drives the real FreeCAD kernel (OpenCASCADE) out of
process via ``freecadcmd`` to answer questions no amount of parsing can answer
— did this parametric feature tree actually build a solid, what does it look
like, and what does it become in STEP.

It exists because FreeCAD reports **no error** for geometry that silently
produces nothing: a boolean whose operands never meet, a fillet radius larger
than the face it rounds, a shell that collapses. Those recompute to a valid,
"Up-to-date" object holding zero solids and volume 0. Only the kernel knows.

FreeCAD is an OPTIONAL dependency. ``available()`` reports whether it is
installed; every other entry point raises :class:`FreeCADKernelError` with an
actionable message when it is not, so callers can degrade gracefully.

Neutral, like its neighbours: standard library only, no forgelab imports, no
knowledge of the ForgeLab IR. Callers pass file paths and object names.

Talking to freecadcmd, the two things that bite:

1. **stdout is noise.** A run emits a banner, a hundred ``(NN %)`` progress
   fragments with no newlines, and a trailing ``Shell cwd was reset ...``.
   Results are therefore framed in a sentinel (``@@FORGELAB@@ ... @@END@@``)
   and recovered by regex; stdout is never scraped.
2. **argv layout is not contractual.** Arguments are embedded into the
   generated script as a JSON literal instead of passed positionally, so
   nothing depends on where freecadcmd leaves the script name in ``sys.argv``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

#: Executable that runs a FreeCAD script with no GUI.
FREECAD_CMD = "freecadcmd"

#: Seconds any single kernel invocation may take before it is killed.
DEFAULT_TIMEOUT = 180

#: Linear deflection (mm) for tessellation. Small enough that a 3 mm fillet
#: reads as curved in a preview, large enough to keep facet counts sane.
DEFAULT_DEVIATION = 0.1

_SENTINEL_START = "@@FORGELAB@@"
_SENTINEL_END = "@@END@@"
_RESULT_RE = re.compile(re.escape(_SENTINEL_START) + r"(.*?)" + re.escape(_SENTINEL_END), re.DOTALL)

_UNAVAILABLE = (
    f"FreeCAD is not installed: {FREECAD_CMD!r} is not on PATH. Install FreeCAD "
    "(https://www.freecad.org/downloads.php) to verify, preview or convert "
    "mechanical geometry; the .FCStd exporter itself needs no FreeCAD."
)


class FreeCADKernelError(RuntimeError):
    """Raised when the FreeCAD kernel is unavailable or a script fails."""


def available() -> bool:
    """True when ``freecadcmd`` is on PATH and the kernel can be driven."""
    return shutil.which(FREECAD_CMD) is not None


def require_available() -> None:
    """Raise :class:`FreeCADKernelError` with install guidance if absent."""
    if not available():
        raise FreeCADKernelError(_UNAVAILABLE)


# --------------------------------------------------------------------------- #
# Script preamble, shared by every operation.
#
# Runs inside FreeCAD's own interpreter, so it may import FreeCAD/Part/Mesh.
# ``ARGS`` is substituted as a JSON literal by _run(). Any exception is
# reported through the same sentinel channel as success, so the caller always
# gets a structured answer rather than a stack trace buried in progress noise.
# --------------------------------------------------------------------------- #
_PREAMBLE = """\
import json, sys
import FreeCAD as App

ARGS = json.loads({args!r})


def _emit(payload):
    sys.stdout.write("{start}" + json.dumps(payload) + "{end}")
    sys.stdout.flush()


def _open(path):
    doc = App.openDocument(path)
    doc.recompute()
    return doc


def _shaped(doc, names):
    \"\"\"Objects carrying a Shape, optionally filtered to ``names``.\"\"\"
    wanted = set(names or [])
    out = []
    for obj in doc.Objects:
        if getattr(obj, "Shape", None) is None:
            continue
        if wanted and obj.Name not in wanted:
            continue
        out.append(obj)
    return out


def _solids(doc, names):
    \"\"\"Shaped objects that really carry solids; NULL shapes are skipped.

    ``.Solids`` on a NULL shape raises out of OCC, so the null test comes first.
    \"\"\"
    return [o for o in _shaped(doc, names) if not o.Shape.isNull() and o.Shape.Solids]


try:
{body}
except Exception as exc:  # noqa: BLE001 - reported to the caller verbatim
    _emit({{"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}})
"""


def _run(body: str, args: dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Run ``body`` inside freecadcmd and return its emitted JSON payload.

    ``body`` is indented into the preamble's ``try`` block and must call
    ``_emit(...)`` exactly once. ``args`` is available to it as ``ARGS``.
    """
    require_available()
    indented = "\n".join("    " + line if line.strip() else line for line in body.splitlines())
    script = _PREAMBLE.format(
        args=json.dumps(args),
        start=_SENTINEL_START,
        end=_SENTINEL_END,
        body=indented,
    )
    with tempfile.TemporaryDirectory(prefix="forgelab-fc-") as tmp:
        script_path = Path(tmp) / "forgelab_kernel.py"
        script_path.write_text(script, encoding="utf-8")
        try:
            proc = subprocess.run(
                [FREECAD_CMD, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired as exc:
            raise FreeCADKernelError(
                f"FreeCAD did not finish within {timeout}s; the geometry may be "
                f"pathological (a huge tessellation or a self-intersecting boolean)"
            ) from exc
    payload = parse_result(proc.stdout)
    if payload is None:
        raise FreeCADKernelError(
            f"FreeCAD produced no result (exit {proc.returncode}). "
            f"stderr: {proc.stderr.strip()[:2000] or '<empty>'}"
        )
    if not payload.get("ok", False):
        raise FreeCADKernelError(f"FreeCAD script failed: {payload.get('error', 'unknown error')}")
    return payload


def parse_result(stdout: str) -> dict[str, Any] | None:
    """Recover the sentinel-framed JSON payload from noisy FreeCAD stdout.

    Returns None when no payload is present (the script died before emitting).
    Split out from :func:`_run` so it can be tested without FreeCAD installed —
    the noise it survives is the whole reason this framing exists.
    """
    match = _RESULT_RE.search(stdout)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #
_INSPECT_BODY = """\
doc = _open(ARGS["path"])
objects = []
for obj in doc.Objects:
    shape = getattr(obj, "Shape", None)
    entry = {
        "name": obj.Name,
        "label": obj.Label,
        "type_id": obj.TypeId,
        "state": [str(s) for s in (obj.State or [])],
        "has_shape": shape is not None,
    }
    if shape is not None:
        # A NULL shape is exactly what this whole module exists to detect, so it
        # must not be fatal here. OCC throws Standard_NullObject out of
        # isValid()/Volume/BoundBox on one (BRepCheck_Analyzer::Init - NULL
        # shape), so the null test has to come first and short-circuit the rest.
        null = bool(shape.isNull())
        entry["null"] = null
        if null:
            entry.update({
                "valid": False, "volume": 0.0, "area": 0.0,
                "solids": 0, "faces": 0, "bbox": None,
            })
        else:
            # Shape.BoundBox is a CONSERVATIVE bound, not the real extent: on
            # curved geometry it is computed from control polygons and comes out
            # too big. A filleted 70x45 plate measured -0.494 to 70.494, half a
            # millimetre of pure fiction on each side, which is exactly the sort
            # of number a caller would read as the part's dimensions.
            # optimalBoundingBox() gives the true extent; fall back if it is
            # unavailable or fails on some shape.
            box = shape.BoundBox
            try:
                box = shape.optimalBoundingBox(True)
            except Exception:
                pass
            entry.update({
                "valid": bool(shape.isValid()),
                "volume": float(shape.Volume),
                "area": float(shape.Area),
                "solids": len(shape.Solids),
                "faces": len(shape.Faces),
                "bbox": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax],
            })
    objects.append(entry)
_emit({"ok": True, "objects": objects})
"""


def inspect_document(path: str | Path, timeout: int = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Open, recompute and report every object's real geometric state.

    Each entry carries ``name``/``label``/``type_id``/``state``/``has_shape``,
    plus — for objects that have a shape — ``valid``, ``null``, ``volume``,
    ``area``, ``solids``, ``faces`` and ``bbox``. Zero ``solids`` or zero
    ``volume`` on a feature that should be solid is the signature of geometry
    that silently built nothing.
    """
    return _run(_INSPECT_BODY, {"path": str(Path(path).resolve())}, timeout)["objects"]


_TESSELLATE_BODY = """\
doc = _open(ARGS["path"])
deviation = ARGS["deviation"]
meshes = []
for obj in _solids(doc, ARGS["names"]):
    verts, facets = obj.Shape.tessellate(deviation)
    meshes.append({
        "name": obj.Name,
        "label": obj.Label,
        "vertices": [[v.x, v.y, v.z] for v in verts],
        "facets": [list(f) for f in facets],
    })
_emit({"ok": True, "meshes": meshes})
"""


def tessellate(
    path: str | Path,
    names: list[str] | None = None,
    deviation: float = DEFAULT_DEVIATION,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Triangulate the document's solids into ``{name, label, vertices, facets}``.

    Coordinates are FreeCAD's own **Z-up millimetres** — no axis conversion is
    applied here. ``names`` restricts the result to those FreeCAD object names
    (see :func:`inspect_document`); passing None takes every solid, which for a
    feature tree includes intermediate features and double-counts geometry, so
    callers normally pass the final/visible set.
    """
    return _run(
        _TESSELLATE_BODY,
        {"path": str(Path(path).resolve()), "names": names, "deviation": deviation},
        timeout,
    )["meshes"]


_CONVERT_BODY = """\
import Part

doc = _open(ARGS["path"])
shapes = _solids(doc, ARGS["names"])
if not shapes:
    raise ValueError("document has no solid geometry to export")
if ARGS["fmt"] == "step":
    Part.export(shapes, ARGS["out"])
else:
    import Mesh
    Mesh.export(shapes, ARGS["out"])
_emit({"ok": True, "objects": [o.Name for o in shapes]})
"""

#: Formats :func:`convert` can write.
CONVERT_FORMATS = ("step", "stl")


def convert(
    path: str | Path,
    out_path: str | Path,
    fmt: str,
    names: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[str]:
    """Convert a ``.FCStd``'s solids to STEP or STL, returning the objects used.

    ``names`` restricts which objects are exported; without it every solid in
    the document is written, which for a PartDesign feature tree means the pad
    AND the pocket AND the body AND the part — four copies of one part. Callers
    should pass the final/visible set.
    """
    if fmt not in CONVERT_FORMATS:
        raise ValueError(f"fmt must be one of {CONVERT_FORMATS}, not {fmt!r}")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return _run(
        _CONVERT_BODY,
        {
            "path": str(Path(path).resolve()),
            "out": str(out.resolve()),
            "fmt": fmt,
            "names": names,
        },
        timeout,
    )["objects"]
