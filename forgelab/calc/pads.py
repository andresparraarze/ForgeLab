"""Standard IC package pad layouts.

Pure geometry: given a package family, pin pitch and pin count, return the
``(x, y)`` offset of every pad from the footprint origin so an agent never has to
work pad coordinates out by hand. Offsets are in millimetres.
"""

from __future__ import annotations

# Default row spacing (distance between the two pad rows) per package family, mm.
_DEFAULT_ROW_SPACING = {"DIP": 7.62, "SOIC": 5.4, "SOP": 5.4}
_DUAL_ROW_FAMILIES = frozenset(_DEFAULT_ROW_SPACING)


def _round(value: float) -> float:
    return round(value, 4)


def _single_row(pitch: float, count: int) -> list[dict[str, object]]:
    start = -(count - 1) * pitch / 2.0
    return [{"number": str(i + 1), "at": [_round(start + i * pitch), 0.0]} for i in range(count)]


def _dual_row(
    family: str, pitch: float, count: int, row_spacing: float | None
) -> list[dict[str, object]]:
    if count % 2 != 0:
        raise ValueError("a dual-row package needs an even pad count")
    per_side = count // 2
    spacing = row_spacing if row_spacing is not None else _DEFAULT_ROW_SPACING[family]
    x = spacing / 2.0
    top = (per_side - 1) * pitch / 2.0
    pads: list[dict[str, object]] = []
    # Left column: pins 1..per_side, top to bottom (pin 1 is top-left).
    for i in range(per_side):
        pads.append({"number": str(i + 1), "at": [_round(-x), _round(top - i * pitch)]})
    # Right column: pins per_side+1..count, bottom to top (counter-clockwise).
    for i in range(per_side):
        pads.append({"number": str(per_side + i + 1), "at": [_round(x), _round(-top + i * pitch)]})
    return pads


def _quad(pitch: float, count: int, row_spacing: float | None) -> list[dict[str, object]]:
    if count % 4 != 0:
        raise ValueError("a QFP needs a pad count divisible by 4")
    per_side = count // 4
    span = (per_side - 1) * pitch
    half = span / 2.0
    offset = row_spacing if row_spacing is not None else half + pitch
    pads: list[dict[str, object]] = []
    number = 0

    def add(x: float, y: float) -> None:
        nonlocal number
        number += 1
        pads.append({"number": str(number), "at": [_round(x), _round(y)]})

    for i in range(per_side):  # left side, top to bottom
        add(-offset, half - i * pitch)
    for i in range(per_side):  # bottom side, left to right
        add(-half + i * pitch, -offset)
    for i in range(per_side):  # right side, bottom to top
        add(offset, -half + i * pitch)
    for i in range(per_side):  # top side, right to left
        add(half - i * pitch, offset)
    return pads


def calculate_pad_positions(
    footprint_type: str,
    pitch: float,
    count: int,
    dual_row: bool = True,
    row_spacing: float | None = None,
) -> list[dict[str, object]]:
    """Pad offsets for a standard IC package, ready to drop into ``Pad.at`` fields.

    Args:
        footprint_type: package family — ``"DIP"``, ``"SOIC"``, ``"SOP"`` (dual-row
            in-line packages) or ``"QFP"`` (quad, pins on all four sides).
            Case-insensitive.
        pitch: centre-to-centre spacing between adjacent pins, in millimetres.
        count: total number of pads. Must be even for a dual-row package and
            divisible by 4 for a QFP.
        dual_row: for DIP/SOIC/SOP, ``True`` lays pins out in two rows; ``False``
            lays them in a single row along the X axis. Ignored for QFP.
        row_spacing: distance between opposing pad rows, in millimetres. Defaults
            per family (DIP 7.62, SOIC/SOP 5.4); for QFP it is the centre-to-side
            distance and defaults to half the pin span plus one pitch.

    Returns:
        A list of ``{"number": str, "at": [x, y]}`` dicts, one per pad, ordered by
        pin number. ``at`` is the pad's offset from the footprint origin in
        millimetres. Numbering follows the standard counter-clockwise convention
        with pin 1 at the top-left.
    """
    family = footprint_type.upper()
    if count < 1:
        raise ValueError("count must be >= 1")
    if pitch <= 0:
        raise ValueError("pitch must be > 0")
    if family == "QFP":
        return _quad(pitch, count, row_spacing)
    if family not in _DUAL_ROW_FAMILIES:
        raise ValueError(
            f"unsupported footprint_type {footprint_type!r}; supported: DIP, SOIC, SOP, QFP"
        )
    if not dual_row:
        return _single_row(pitch, count)
    return _dual_row(family, pitch, count, row_spacing)
