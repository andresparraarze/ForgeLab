"""KiCad's own DRC as the last word on a board.

The mechanical domain has always had a ground truth: `verify_document` builds
the part in the real OpenCASCADE kernel and reports what actually got made,
because FreeCAD reports no error for geometry that silently produces nothing.
Hardware had no equivalent. `tests/external_tools.py` states the intent —
"a board is checked by running kicad-cli's own DRC" — but that only ever
happened in three tests. Nothing in `forgelab/` ever asked KiCad anything, so an
agent could build, place, route and fab-check a board and never find out that
KiCad considered 23 of its footprints wrong and two of its nets shorted.

This is that missing half. It exports the document, runs `kicad-cli pcb drc`,
and returns the violations in the shape `check_fabrication` already uses, so a
caller reads one kind of result either way.

What it adds over ForgeLab's own checks is everything ForgeLab declines to
reimplement: real copper-pour fills with their clearances and thermal reliefs,
courtyard overlap, solder-mask bridging, silkscreen over copper, hole-to-hole
spacing, and connectivity computed from filled zones rather than approximated.
`forgelab.validation.electrical` documents its own blind spot on poured nets and
points here; this is where that answer comes from.

KiCad is an OPTIONAL dependency, like FreeCAD next door: `available()` reports
whether it is installed and every entry point raises `VerifyError` with an
actionable message when it is not.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.spec import Domain, ForgeDocument
from forgelab.verify.freecad import VerifyError

#: KiCad's command-line driver. Ships with KiCad 7 and later.
KICAD_CLI = "kicad-cli"

#: Seconds a DRC run may take before it is killed. Filling the copper pours on a
#: dense board is the slow part; 300s is generous for a board ForgeLab produced.
DEFAULT_TIMEOUT = 300

_UNAVAILABLE = (
    f"KiCad is not installed: {KICAD_CLI!r} is not on PATH. Install KiCad "
    "(https://www.kicad.org/download/) to check a board against KiCad's own "
    "DRC; exporting a .kicad_pcb itself needs no KiCad."
)


def available() -> bool:
    """Whether ``kicad-cli`` can be run on this machine."""
    return shutil.which(KICAD_CLI) is not None


@lru_cache(maxsize=1)
def supports_refill_zones() -> bool:
    """Whether this ``kicad-cli`` accepts ``--refill-zones``.

    The flag arrived after KiCad 9 — 9.0.9 rejects it outright with "Unknown
    argument", which fails the whole run rather than degrading. Asking the tool
    what it accepts, instead of assuming the version the author happened to have
    installed, is the difference between working on one machine and working.
    """
    if not available():
        return False
    try:
        proc = subprocess.run(
            [KICAD_CLI, "pcb", "drc", "--help"],
            capture_output=True, text=True, check=False, timeout=30,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - defensive
        return False
    return "--refill-zones" in (proc.stdout + proc.stderr)


def drc_argv(board: Path | str, report: Path | str, fill_zones: bool = True) -> list[str]:
    """The ``kicad-cli pcb drc`` command line for this machine's KiCad.

    Shared with the tests so there is one place that knows which flags this
    version has.
    """
    argv = [
        KICAD_CLI, "pcb", "drc",
        "--severity-all",
        "--format", "json",
        "-o", str(report),
    ]  # fmt: skip
    if fill_zones and supports_refill_zones():
        # Without it KiCad measures the pours as drawn rather than as filled,
        # reporting clearance and connectivity the fabricated board would not
        # have. Where the flag does not exist, KiCad uses whatever fill the file
        # carries — ForgeLab writes none, so pours read as empty and a poured
        # net's pads show as unconnected. Reported honestly either way.
        argv.append("--refill-zones")
    argv.append(str(board))
    return argv


def verify_document(
    document: ForgeDocument, timeout: int | None = None, fill_zones: bool = True
) -> dict[str, Any]:
    """Run KiCad's DRC over ``document`` and report what KiCad found.

    Returns ``{"verified", "errors", "warnings", "unconnected", "violations",
    "checked_by"}``. ``errors`` and ``warnings`` are human-readable strings in
    the same style as ``check_fabrication``; ``violations`` keeps the structured
    detail, each entry carrying its ``type``, ``severity``, ``description`` and
    the items involved.

    ``unconnected`` is KiCad's own connectivity verdict, computed from filled
    copper — the number ``forgelab.validation.electrical`` cannot produce.
    """
    if document.domain != Domain.HARDWARE:
        raise VerifyError(
            f"KiCad DRC applies to hardware documents, not {document.domain.value!r} — "
            "use verify_geometry's mechanical path for parts"
        )
    if not available():
        raise VerifyError(_UNAVAILABLE)

    with tempfile.TemporaryDirectory(prefix="forgelab-drc-") as tmp:
        board = Path(tmp) / "board.kicad_pcb"
        report = Path(tmp) / "drc.json"
        board.write_bytes(KiCadExporter().from_ir(document))
        argv = drc_argv(board, report, fill_zones=fill_zones)
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, check=False,
                timeout=timeout or DEFAULT_TIMEOUT,
            )  # fmt: skip
        except subprocess.TimeoutExpired as exc:
            raise VerifyError(
                f"KiCad DRC did not finish within {timeout or DEFAULT_TIMEOUT}s"
            ) from exc
        if not report.exists():
            detail = (proc.stderr or proc.stdout or "").strip()[:400]
            raise VerifyError(f"KiCad could not check the board: {detail or 'no output'}")
        payload = json.loads(report.read_text(encoding="utf-8"))

    return _summarize(payload)


def _describe(violation: dict[str, Any]) -> str:
    """One violation as a line a person (or a model) can act on."""
    where = ""
    items = violation.get("items") or []
    if items:
        parts = [str(item.get("description", "")).strip() for item in items[:2]]
        positions = [item.get("pos") for item in items[:1] if isinstance(item.get("pos"), dict)]
        where = " — " + "; ".join(p for p in parts if p)
        if positions:
            pos = positions[0]
            where += f" at ({pos.get('x')}, {pos.get('y')})"
    return f"[{violation.get('type', '?')}] {violation.get('description', '')}{where}"


def _summarize(payload: dict[str, Any]) -> dict[str, Any]:
    violations = list(payload.get("violations") or [])
    unconnected = list(payload.get("unconnected_items") or [])
    # KiCad reports unconnected items in their own section, not among the
    # violations; they are errors by any useful definition, so they are folded
    # in here rather than left for the caller to notice separately.
    everything = violations + unconnected

    errors = [_describe(v) for v in everything if v.get("severity") == "error"]
    warnings = [_describe(v) for v in everything if v.get("severity") == "warning"]
    return {
        "verified": not errors,
        "errors": errors,
        "warnings": warnings,
        "unconnected": len(unconnected),
        "violations": everything,
        "checked_by": f"{KICAD_CLI} pcb drc",
    }
