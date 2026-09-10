"""One answer to "where is this component's copper, and how big is it?".

Five places need that answer and must agree on it: the KiCad exporter (which
draws the copper), the Gerber exporter (which draws it again, in another
format), the placer (which reserves room for it), the router (which routes
around it) and the fabrication checker (which measures the gaps between it).
They already shared the *invented* answer — ``pad_default_size`` and
``pad_grid_offset`` from ``forgelab.spec.hardware``. This module is where they
share the *real* one.

The real one comes from the footprint the component names. When
``Resistor_SMD:R_0603_1608Metric`` resolves against the installed KiCad
libraries, its pads are at ±0.825mm and measure 0.8x0.95 — not the 1.6mm squares
at the origin the fallback produces, which are both too big and, because they
coincide, an electrical short. Disagreement between the exporter and the router
is the specific failure this prevents: copper routed through a pad that is
larger on the board than it was in the router's model.

Layering: ``spec`` defines the IR and ``formats`` reads files; both are leaves.
This sits directly above them and below every consumer, so neither leaf has to
learn about the other.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

from forgelab.formats import kicad_library
from forgelab.spec.hardware import pad_default_size, pad_grid_offset


class ResolvedPad(NamedTuple):
    """One pad's copper in the component's own Y-up frame, before placement.

    ``x``/``y`` are footprint-local and unrotated — callers apply the
    component's rotation and origin, as they always have.
    """

    number: str
    net: str
    x: float
    y: float
    width: float
    height: float
    shape: str
    #: The pad's own rotation within the footprint (degrees). KiCad library
    #: pads carry one — a QFP's side pins are the same rectangle turned 90 —
    #: and it composes with the component's placement angle.
    rotation: float
    #: Round-hole diameter (mm), or None for an SMD pad or a slot.
    drill: float | None
    #: ``[width, height]`` of a slotted hole, or None.
    oval: list[float] | None
    plated: bool
    #: False when the position was invented by the fallback grid rather than
    #: stated by the IR or the library. The router refuses to route to these:
    #: connecting to copper whose location is a guess is worse than reporting
    #: the net as unrouted.
    positioned: bool
    #: True when the pad is copper on every layer, not just the component's.
    through_hole: bool

    @property
    def half_extents(self) -> tuple[float, float]:
        """Half-width and half-height of the pad's axis-aligned bounding box."""
        return self.width / 2, self.height / 2

    def rotated_half_extents(self, rotation: float = 0.0) -> tuple[float, float]:
        """Half-extents of the pad rectangle placed at ``rotation``.

        The pad's own in-footprint rotation composes with the component's.
        """
        theta = math.radians(self.rotation + rotation)
        cos_r, sin_r = abs(math.cos(theta)), abs(math.sin(theta))
        return (
            (self.width * cos_r + self.height * sin_r) / 2,
            (self.width * sin_r + self.height * cos_r) / 2,
        )


def _as_pairs(value: Any) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


def resolve(footprint: str | None, pads: list[dict]) -> list[ResolvedPad]:
    """This component's pad copper, preferring the real library footprint.

    When ``footprint`` names a footprint the installed KiCad libraries have, the
    library defines the pad set and its geometry, and the IR supplies only the
    netlist — matched by pad number. That direction is deliberate: a stock
    library footprint *is* whatever the library says it is, so IR geometry that
    disagrees is wrong rather than overriding. A component needing bespoke
    copper should not claim a stock part.

    Otherwise the historical fallback applies unchanged: an explicit ``at`` and
    ``size`` when the IR states them, the shared pitch-aware default and
    deterministic grid when it does not.
    """
    clean = [p for p in pads if isinstance(p, dict)]
    library = kicad_library.pad_geometry(footprint) if footprint else None
    if library:
        return _from_library(library, clean)
    return _from_ir(clean)


def _from_library(library: tuple[dict, ...], pads: list[dict]) -> list[ResolvedPad]:
    nets = {str(p.get("number", "")): str(p.get("net", "")) for p in pads}
    out: list[ResolvedPad] = []
    for pad in library:
        number = pad["number"]
        layers = pad["layers"]
        through = pad["drill"] is not None or pad["oval"] is not None
        out.append(
            ResolvedPad(
                number=number,
                # A library pad the IR never mentions is real copper with no
                # net — a mounting or thermal pad the design leaves floating.
                net=nets.get(number, ""),
                x=pad["at"][0],
                y=pad["at"][1],
                width=pad["size"][0],
                height=pad["size"][1],
                shape=pad["shape"],
                rotation=pad["rotation"],
                drill=pad["drill"],
                oval=pad["oval"],
                plated=pad["plated"],
                positioned=True,
                through_hole=through or any(x.startswith("*.") for x in layers),
            )
        )
    return out


def _from_ir(pads: list[dict]) -> list[ResolvedPad]:
    default = pad_default_size([p.get("at") for p in pads])
    out: list[ResolvedPad] = []
    for index, pad in enumerate(pads):
        offset = _as_pairs(pad.get("at"))
        positioned = offset is not None
        x, y = offset if offset is not None else pad_grid_offset(index, len(pads))
        size = _as_pairs(pad.get("size"))
        width, height = size if size is not None else (default, default)
        drill = pad.get("drill") if isinstance(pad.get("drill"), dict) else None
        diameter = None
        oval = None
        plated = True
        if drill is not None:
            raw = drill.get("diameter")
            diameter = float(raw) if isinstance(raw, (int, float)) else None
            raw_oval = _as_pairs(drill.get("oval"))
            oval = list(raw_oval) if raw_oval is not None else None
            plated = bool(drill.get("plated", True))
        out.append(
            ResolvedPad(
                number=str(pad.get("number", "")),
                net=str(pad.get("net", "")),
                x=x,
                y=y,
                width=width,
                height=height,
                shape=str(pad.get("shape") or "roundrect"),
                rotation=0.0,
                drill=diameter,
                oval=oval,
                plated=plated,
                positioned=positioned,
                through_hole=drill is not None,
            )
        )
    return out


def unknown_pad_numbers(footprint: str | None, pads: list[dict]) -> list[str]:
    """IR pad numbers the named library footprint does not have.

    A netlist error rather than a geometry one — the design wires a pin the part
    does not expose, which usually means the wrong footprint or a typo'd number.
    Empty when the footprint does not resolve, since then nothing is known.
    """
    library = kicad_library.pad_geometry(footprint) if footprint else None
    if not library:
        return []
    have = {p["number"] for p in library}
    return sorted({str(p.get("number", "")) for p in pads if isinstance(p, dict)} - have - {""})


def courtyard(footprint: str | None, rotation: float = 0.0) -> tuple[float, float, float, float]:
    """The footprint's courtyard extents, rotated, or an empty box if unknown.

    Returns ``(x0, y0, x1, y1)`` in the component's own frame. An empty box
    ``(0, 0, 0, 0)`` means "the library has nothing to say", which callers union
    with the pad extents so the pads alone still define the area.
    """
    box = kicad_library.courtyard_bbox(footprint) if footprint else None
    if box is None:
        return (0.0, 0.0, 0.0, 0.0)
    x0, y0, x1, y1 = box
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    theta = math.radians(rotation)
    cos_r, sin_r = math.cos(theta), math.sin(theta)
    turned = [(x * cos_r - y * sin_r, x * sin_r + y * cos_r) for x, y in corners]
    xs = [p[0] for p in turned]
    ys = [p[1] for p in turned]
    return (min(xs), min(ys), max(xs), max(ys))
