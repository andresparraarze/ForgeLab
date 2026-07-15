"""Gerber (RS-274X) + Excellon exporter: a fab-ready layer set in one zip.

Produces the standard file set a PCB fab accepts: front/back copper (routed
tracks, via annulars and flashed pad apertures), front/back soldermask (pad
openings with a standard expansion), front/back silkscreen (reference
designators in a built-in stroke font), the board outline (Edge.Cuts) and an
Excellon drill file with one hole per via. Everything is plain text generated
with the standard library; coordinates use the absolute ``%FSLAX46Y46*%``
format (millimetres, 6 decimal places) and every layer carries proper
aperture definitions before its draw commands, so the output opens in real
Gerber viewers rather than merely resembling the format.

Coordinate frames: the IR is Y-up (see ``forgelab.spec.hardware``) and
RS-274X/Excellon are natively Y-up too, so **coordinates pass through
unchanged — deliberately no flip here** (the KiCad exporter is the one that
mirrors Y into KiCad's Y-down file frame).

Scope notes: the ForgeLab pad model has no through-hole concept (pads are
SMD, as in the KiCad exporter), so the drill file contains via holes only.
Pads without a physical ``at`` fall back to the same deterministic grid the
KiCad exporter uses, keeping the two outputs geometrically consistent.

Depends only on ``forgelab.spec`` and ``forgelab.formats`` (boundary rule).
"""

from __future__ import annotations

import math

from forgelab.exporters.base import Exporter
from forgelab.formats import write_archive
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_TRACK,
    NODE_VIA,
    ForgeDocument,
    pad_default_size,
    pad_grid_offset,
)

# Soldermask opening expansion per side (mm), a common fab default.
_MASK_EXPANSION = 0.05

_OUTLINE_WIDTH = 0.1  # Edge.Cuts stroke (mm)
_SILK_STROKE = 0.15  # silkscreen pen width (mm)
_SILK_HEIGHT = 1.0  # reference-designator character height (mm)


# Minimal stroke font on a 2x3 unit grid: char -> line segments
# (x1, y1, x2, y2), y up. Enough for reference designators (A-Z, 0-9, _-+.).
_FONT: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "0": ((0, 0, 2, 0), (2, 0, 2, 3), (2, 3, 0, 3), (0, 3, 0, 0)),
    "1": ((1, 0, 1, 3), (0.4, 2.4, 1, 3), (0.4, 0, 1.6, 0)),
    "2": ((0, 3, 2, 3), (2, 3, 2, 1.5), (2, 1.5, 0, 1.5), (0, 1.5, 0, 0), (0, 0, 2, 0)),
    "3": ((0, 3, 2, 3), (2, 3, 2, 0), (2, 0, 0, 0), (0, 1.5, 2, 1.5)),
    "4": ((0, 3, 0, 1.5), (0, 1.5, 2, 1.5), (2, 3, 2, 0)),
    "5": ((2, 3, 0, 3), (0, 3, 0, 1.5), (0, 1.5, 2, 1.5), (2, 1.5, 2, 0), (2, 0, 0, 0)),
    "6": ((2, 3, 0, 3), (0, 3, 0, 0), (0, 0, 2, 0), (2, 0, 2, 1.5), (2, 1.5, 0, 1.5)),
    "7": ((0, 3, 2, 3), (2, 3, 1, 0)),
    "8": ((0, 0, 2, 0), (2, 0, 2, 3), (2, 3, 0, 3), (0, 3, 0, 0), (0, 1.5, 2, 1.5)),
    "9": ((0, 0, 2, 0), (2, 0, 2, 3), (2, 3, 0, 3), (0, 3, 0, 1.5), (0, 1.5, 2, 1.5)),
    "A": ((0, 0, 0, 3), (2, 0, 2, 3), (0, 3, 2, 3), (0, 1.5, 2, 1.5)),
    "B": (
        (0, 0, 0, 3),
        (0, 3, 1.8, 3),
        (1.8, 3, 1.8, 1.5),
        (0, 1.5, 2, 1.5),
        (2, 1.5, 2, 0),
        (2, 0, 0, 0),
    ),
    "C": ((2, 3, 0, 3), (0, 3, 0, 0), (0, 0, 2, 0)),
    "D": (
        (0, 0, 0, 3),
        (0, 3, 1.6, 3),
        (1.6, 3, 2, 2.4),
        (2, 2.4, 2, 0.6),
        (2, 0.6, 1.6, 0),
        (1.6, 0, 0, 0),
    ),
    "E": ((2, 3, 0, 3), (0, 3, 0, 0), (0, 0, 2, 0), (0, 1.5, 1.6, 1.5)),
    "F": ((2, 3, 0, 3), (0, 3, 0, 0), (0, 1.5, 1.6, 1.5)),
    "G": ((2, 3, 0, 3), (0, 3, 0, 0), (0, 0, 2, 0), (2, 0, 2, 1.5), (2, 1.5, 1, 1.5)),
    "H": ((0, 0, 0, 3), (2, 0, 2, 3), (0, 1.5, 2, 1.5)),
    "I": ((1, 0, 1, 3), (0.4, 3, 1.6, 3), (0.4, 0, 1.6, 0)),
    "J": ((2, 3, 2, 0), (2, 0, 0, 0), (0, 0, 0, 1)),
    "K": ((0, 0, 0, 3), (0, 1.5, 2, 3), (0, 1.5, 2, 0)),
    "L": ((0, 3, 0, 0), (0, 0, 2, 0)),
    "M": ((0, 0, 0, 3), (0, 3, 1, 1.5), (1, 1.5, 2, 3), (2, 3, 2, 0)),
    "N": ((0, 0, 0, 3), (0, 3, 2, 0), (2, 0, 2, 3)),
    "O": ((0, 0, 2, 0), (2, 0, 2, 3), (2, 3, 0, 3), (0, 3, 0, 0)),
    "P": ((0, 0, 0, 3), (0, 3, 2, 3), (2, 3, 2, 1.5), (2, 1.5, 0, 1.5)),
    "Q": ((0, 0, 2, 0), (2, 0, 2, 3), (2, 3, 0, 3), (0, 3, 0, 0), (1.2, 0.8, 2.2, -0.2)),
    "R": ((0, 0, 0, 3), (0, 3, 2, 3), (2, 3, 2, 1.5), (2, 1.5, 0, 1.5), (0.8, 1.5, 2, 0)),
    "S": ((2, 3, 0, 3), (0, 3, 0, 1.5), (0, 1.5, 2, 1.5), (2, 1.5, 2, 0), (2, 0, 0, 0)),
    "T": ((0, 3, 2, 3), (1, 3, 1, 0)),
    "U": ((0, 3, 0, 0), (0, 0, 2, 0), (2, 0, 2, 3)),
    "V": ((0, 3, 1, 0), (1, 0, 2, 3)),
    "W": ((0, 3, 0, 0), (0, 0, 1, 1.5), (1, 1.5, 2, 0), (2, 0, 2, 3)),
    "X": ((0, 0, 2, 3), (0, 3, 2, 0)),
    "Y": ((0, 3, 1, 1.5), (2, 3, 1, 1.5), (1, 1.5, 1, 0)),
    "Z": ((0, 3, 2, 3), (2, 3, 0, 0), (0, 0, 2, 0)),
    "-": ((0.4, 1.5, 1.6, 1.5),),
    "_": ((0, 0, 2, 0),),
    "+": ((0.2, 1.5, 1.8, 1.5), (1, 0.7, 1, 2.3)),
    ".": ((0.9, 0, 1.1, 0),),
}
_FONT_GRID_HEIGHT = 3.0
_FONT_ADVANCE = 3.0  # grid units per character (2 wide + 1 space)


def _coord(mm: float) -> int:
    """A millimetre value in the file's 4.6 fixed format."""
    return round(mm * 1_000_000)


class _GerberFile:
    """One RS-274X layer: aperture table + draw/flash commands."""

    def __init__(self, function: str) -> None:
        self._function = function
        self._apertures: dict[str, int] = {}  # template -> D-code
        self._body: list[str] = []
        self._current: int | None = None

    def aperture(self, template: str) -> int:
        """D-code for an aperture template like ``C,0.250000`` (deduplicated)."""
        if template not in self._apertures:
            self._apertures[template] = 10 + len(self._apertures)
        return self._apertures[template]

    def _select(self, dcode: int) -> None:
        if self._current != dcode:
            self._body.append(f"D{dcode}*")
            self._current = dcode

    def flash(self, x: float, y: float, dcode: int) -> None:
        self._select(dcode)
        self._body.append(f"X{_coord(x)}Y{_coord(y)}D03*")

    def line(self, x1: float, y1: float, x2: float, y2: float, dcode: int) -> None:
        self._select(dcode)
        self._body.append(f"X{_coord(x1)}Y{_coord(y1)}D02*")
        self._body.append(f"X{_coord(x2)}Y{_coord(y2)}D01*")

    def render(self) -> str:
        lines = [
            "%TF.GenerationSoftware,ForgeLab*%",
            f"%TF.FileFunction,{self._function}*%",
            "%FSLAX46Y46*%",
            "%MOMM*%",
            "G01*",
            "%LPD*%",
        ]
        for template, dcode in self._apertures.items():
            lines.append(f"%ADD{dcode}{template}*%")
        lines.extend(self._body)
        lines.append("M02*")
        return "\n".join(lines) + "\n"


def _rotate_offset(px: float, py: float, rotation_deg: float) -> tuple[float, float]:
    """Rotate a pad offset by the component rotation.

    The IR is Y-up with positive rotation counterclockwise (see
    ``forgelab.spec.hardware``): ``(1, 0)`` at 90 degrees lands at ``(0, 1)``.
    Duplicates the formula in ``forgelab.layout`` (the boundary rule keeps
    exporters off that package) so the Gerbers agree with both the router and
    KiCad's rendering of the Y-flipped export.
    """
    if rotation_deg % 360.0 == 0.0:
        return px, py
    theta = math.radians(rotation_deg)
    c, s = math.cos(theta), math.sin(theta)
    return px * c - py * s, px * s + py * c


def _pad_template(width: float, height: float, shape: str) -> str:
    if shape == "circle":
        return f"C,{width:.6f}"
    if shape == "oval":
        return f"O,{width:.6f}X{height:.6f}"
    return f"R,{width:.6f}X{height:.6f}"  # rect / roundrect / anything else


def _stroke_text(gerber: _GerberFile, text: str, x: float, y: float, dcode: int) -> None:
    """Draw ``text`` with its lower-left corner at (x, y) in the stroke font."""
    scale = _SILK_HEIGHT / _FONT_GRID_HEIGHT
    for i, char in enumerate(text.upper()):
        segments = _FONT.get(char)
        if not segments:
            continue  # unknown character: leave a space
        ox = x + i * _FONT_ADVANCE * scale
        for x1, y1, x2, y2 in segments:
            gerber.line(ox + x1 * scale, y + y1 * scale, ox + x2 * scale, y + y2 * scale, dcode)


class GerberExporter(Exporter):
    """Export ForgeLab hardware IR to a zip of RS-274X Gerbers + Excellon drill."""

    tool_name = "gerber"

    def from_ir(self, document: ForgeDocument) -> bytes:
        copper = {"F.Cu": _GerberFile("Copper,L1,Top"), "B.Cu": _GerberFile("Copper,L2,Bot")}
        mask = {"F.Cu": _GerberFile("Soldermask,Top"), "B.Cu": _GerberFile("Soldermask,Bot")}
        silk = {"F.Cu": _GerberFile("Legend,Top"), "B.Cu": _GerberFile("Legend,Bot")}
        edge = _GerberFile("Profile,NP")

        # Component pads: copper flash + mask opening on the component's side,
        # reference designator on that side's silkscreen.
        for node in document.walk():
            if node.type != NODE_COMPONENT:
                continue
            props = node.props
            at = props.get("at") or [0.0, 0.0]
            cx, cy = float(at[0]), float(at[1])
            rotation = float(at[2]) if len(at) >= 3 else 0.0
            side = "B.Cu" if str(props.get("layer", "F.Cu")) == "B.Cu" else "F.Cu"
            pads = [p for p in (props.get("pads") or []) if isinstance(p, dict)]
            # Size-less pads render the shared pitch-aware default — the same
            # copper the KiCad export and the layout/validation tools assume.
            default = pad_default_size([p.get("at") for p in pads])
            max_pad_y = 0.0
            for index, pad in enumerate(pads):
                offset = pad.get("at")
                if isinstance(offset, list) and len(offset) == 2:
                    px, py = _rotate_offset(float(offset[0]), float(offset[1]), rotation)
                else:
                    # The fallback grid is footprint-local, so it rotates with
                    # the component exactly like an explicit offset (KiCad
                    # rotates footprint-local coordinates natively).
                    gx, gy = pad_grid_offset(index, len(pads))
                    px, py = _rotate_offset(gx, gy, rotation)
                size = pad.get("size")
                if isinstance(size, list) and len(size) == 2:
                    width, height = float(size[0]), float(size[1])
                else:
                    width, height = default, default
                shape = str(pad.get("shape") or "roundrect")
                # The aperture rotates with the pad: swap the rectangle/oval
                # dimensions at 90/270. An arbitrary angle cannot be expressed
                # with a standard R/O aperture, so refuse it honestly rather
                # than emit copper KiCad would render elsewhere.
                if shape != "circle" and rotation % 90.0 != 0.0:
                    reference = str(props.get("reference", "") or node.id)
                    raise ValueError(
                        f"component {reference!r} is rotated {rotation:g} degrees; Gerber "
                        "rectangular/oval pad apertures support only multiples of 90 — "
                        "set the rotation to 0/90/180/270 or use circle pads"
                    )
                if rotation % 180.0 == 90.0:
                    width, height = height, width
                copper[side].flash(
                    cx + px, cy + py, copper[side].aperture(_pad_template(width, height, shape))
                )
                mask[side].flash(
                    cx + px,
                    cy + py,
                    mask[side].aperture(
                        _pad_template(
                            width + 2 * _MASK_EXPANSION, height + 2 * _MASK_EXPANSION, shape
                        )
                    ),
                )
                max_pad_y = max(max_pad_y, py + height / 2)
            reference = str(props.get("reference", "") or node.id)
            if reference:
                text_width = len(reference) * _FONT_ADVANCE * (_SILK_HEIGHT / _FONT_GRID_HEIGHT)
                _stroke_text(
                    silk[side],
                    reference,
                    cx - text_width / 2,
                    cy + max_pad_y + 0.4,
                    silk[side].aperture(f"C,{_SILK_STROKE:.6f}"),
                )

        # Routed copper: tracks on their layer, via annulars on both layers.
        drills: list[tuple[float, float, float]] = []  # (x, y, drill)
        for node in document.walk():
            if node.type == NODE_TRACK:
                props = node.props
                target = copper.get(str(props.get("layer", "F.Cu")))
                if target is None:
                    continue
                width = float(props.get("width", 0.25))
                start, end = props.get("start") or [0, 0], props.get("end") or [0, 0]
                target.line(
                    float(start[0]),
                    float(start[1]),
                    float(end[0]),
                    float(end[1]),
                    target.aperture(f"C,{width:.6f}"),
                )
            elif node.type == NODE_VIA:
                props = node.props
                at = props.get("at") or [0, 0]
                x, y = float(at[0]), float(at[1])
                size = float(props.get("size", 0.8))
                for layer_file in copper.values():
                    layer_file.flash(x, y, layer_file.aperture(f"C,{size:.6f}"))
                drills.append((x, y, float(props.get("drill", 0.4))))

        # Board outline.
        board = next((n for n in document.walk() if n.type == NODE_BOARD), None)
        edge_dcode = edge.aperture(f"C,{_OUTLINE_WIDTH:.6f}")
        for seg in (board.props.get("outline") if board else None) or []:
            if not isinstance(seg, dict):
                continue
            start, end = seg.get("start"), seg.get("end")
            if isinstance(start, list) and isinstance(end, list):
                edge.line(
                    float(start[0]), float(start[1]), float(end[0]), float(end[1]), edge_dcode
                )

        return write_archive(
            {
                "F_Cu.gbr": copper["F.Cu"].render(),
                "B_Cu.gbr": copper["B.Cu"].render(),
                "F_Mask.gbr": mask["F.Cu"].render(),
                "B_Mask.gbr": mask["B.Cu"].render(),
                "F_Silkscreen.gbr": silk["F.Cu"].render(),
                "B_Silkscreen.gbr": silk["B.Cu"].render(),
                "Edge_Cuts.gbr": edge.render(),
                "drill.drl": _excellon(drills),
            }
        )


def _excellon(drills: list[tuple[float, float, float]]) -> str:
    """An Excellon drill file: one plated hole per via, tools grouped by size."""
    tools: dict[float, int] = {}
    for _x, _y, drill in drills:
        if drill not in tools:
            tools[drill] = len(tools) + 1
    lines = ["M48", ";GenerationSoftware,ForgeLab", "METRIC,TZ"]
    for drill, number in sorted(tools.items(), key=lambda item: item[1]):
        lines.append(f"T{number}C{drill:.3f}")
    lines.append("%")
    for drill, number in sorted(tools.items(), key=lambda item: item[1]):
        lines.append(f"T{number}")
        for x, y, hole in drills:
            if hole == drill:
                lines.append(f"X{x:.3f}Y{y:.3f}")
    lines.append("M30")
    return "\n".join(lines) + "\n"
