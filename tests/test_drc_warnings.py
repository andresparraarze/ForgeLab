"""The two cosmetic DRC warnings the through-hole Arduino Uno board exposed.

KiCad reported 12 ``silk_over_copper`` warnings (every footprint's reference
designator sat at the footprint origin, in the middle of its own pad row) and
2 ``hole_to_hole`` warnings (the router dropped a via onto a through-hole pad
of the *same* net, whose plated barrel already joined the layers). Both are
pinned here against the real Uno fixture, and the last test re-runs kicad-cli's
own DRC as the ground truth.
"""

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.formats import parse
from forgelab.layout.placement import component_rotation, place_components, rotate_offset
from forgelab.layout.routing import route_document
from forgelab.spec import ForgeDocument, Node

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _uno() -> ForgeDocument:
    """The bundled Arduino Uno, auto-placed — the fixture both bugs came from."""
    doc = ForgeDocument.model_validate(
        json.loads((_EXAMPLES / "hardware/arduino_uno.forge.json").read_text())
    )
    placed = place_components(doc)
    for node in doc.walk():
        if node.id in placed["placements"]:
            node.props["at"] = placed["placements"][node.id]
    return doc


def _routed(doc: ForgeDocument, result: dict) -> ForgeDocument:
    nodes = list(doc.nodes)
    nodes += [Node(id=f"track_{i}", type="track", props=t) for i, t in enumerate(result["tracks"])]
    nodes += [Node(id=f"via_{i}", type="via", props=v) for i, v in enumerate(result["vias"])]
    nodes += [Node(id=f"zone_{i}", type="zone", props=z) for i, z in enumerate(result["zones"])]
    return doc.model_copy(update={"nodes": nodes})


def _footprints(text: str) -> list[list]:
    return [c for c in parse(text) if isinstance(c, list) and c and c[0] == "footprint"]


def _prop(footprint: list, name: str) -> list:
    return next(
        c
        for c in footprint
        if isinstance(c, list) and c and c[0] == "property" and c[1] == name  # fmt: skip
    )


def _child(node: list, tag: str) -> list:
    return next(c for c in node if isinstance(c, list) and c and c[0] == tag)


def _through_hole_pads(doc: ForgeDocument) -> list[tuple[str, float, float, float, float]]:
    """``(net, x, y, width, height)`` for every positioned through-hole pad."""
    pads = []
    for node in doc.walk():
        if node.type != "component":
            continue
        at = node.props.get("at") or [0.0, 0.0]
        rotation = component_rotation(node.props)
        for pad in node.props.get("pads") or []:
            offset = pad.get("at")
            if not isinstance(pad.get("drill"), dict) or not isinstance(offset, list):
                continue
            rx, ry = rotate_offset(float(offset[0]), float(offset[1]), rotation)
            width, height = pad.get("size") or [1.7, 1.7]
            pads.append(
                (str(pad.get("net", "")), at[0] + rx, at[1] + ry, float(width), float(height))
            )
    return pads


# ------------------------------------------------------- silkscreen placement


def test_reference_designator_clears_its_own_pads():
    """Every Uno reference sits outside the vertical span of its component's pads.

    The old export emitted a bare ``(property "Reference" ...)``, which KiCad
    puts at the footprint origin — inside the pad row of a centred part.
    """
    doc = _uno()
    text = KiCadExporter().from_ir(doc).decode()
    footprints = _footprints(text)
    assert footprints
    for footprint in footprints:
        pads = [c for c in footprint if isinstance(c, list) and c and c[0] == "pad"]
        spans = [(_child(p, "at")[2], _child(p, "size")[2] / 2) for p in pads]
        top = min(y - half for y, half in spans)
        bottom = max(y + half for y, half in spans)
        ref_y = _prop(footprint, "Reference")[3][2]
        assert ref_y < top or ref_y > bottom, footprint[1]


def test_reference_is_on_silkscreen_and_value_on_fab():
    """Value moves to F.Fab — a fabrication layer that cannot collide with copper,
    which is exactly where the KiCad library footprints put it."""
    footprint = _footprints(KiCadExporter().from_ir(_uno()).decode())[0]
    assert str(_child(_prop(footprint, "Reference"), "layer")[1]) == "F.SilkS"
    assert str(_child(_prop(footprint, "Value"), "layer")[1]) == "F.Fab"


def test_reference_steps_away_from_a_neighbouring_parts_pads():
    """Clearing only your own pads is not enough on a densely packed board.

    U2 on the auto-placed Uno lands close enough to J_ANALOG that the default
    spot above the part still crossed a *neighbour's* pad, so the placement had
    to try the other side. The Uno's headers, which have room above them, keep
    the library-convention position.
    """
    doc = _uno()
    text = KiCadExporter().from_ir(doc).decode()

    def side(reference: str) -> str:
        footprint = next(f for f in _footprints(text) if _prop(f, "Reference")[2] == reference)
        pads = [c for c in footprint if isinstance(c, list) and c and c[0] == "pad"]
        top = min(_child(p, "at")[2] - _child(p, "size")[2] / 2 for p in pads)
        ref_y = _prop(footprint, "Reference")[3][2]
        return "above" if ref_y < top else "below"

    assert side("U2") == "below"
    assert side("J_ANALOG") == "above"


# --------------------------------------------------- redundant via suppression


def test_router_places_no_via_on_a_same_net_through_hole_pad():
    """A plated pad barrel already joins the layers, so a via on it is a second
    drill hole for nothing — which is what KiCad flags as ``hole_to_hole``."""
    doc = _uno()
    result = route_document(doc)
    pads = _through_hole_pads(doc)
    assert pads, "the Uno fixture must still have through-hole header pads"
    for via in result["vias"]:
        vx, vy = via["at"]
        for net, px, py, width, height in pads:
            on_pad = abs(vx - px) <= width / 2 and abs(vy - py) <= height / 2
            assert not (on_pad and net == via["net"]), f"redundant via at {via['at']} on {net}"


def test_suppressing_redundant_vias_does_not_cost_routed_nets():
    """The fix drops drill holes, not connections: the Uno still routes the same
    nets and still auto-pours GND and +5V."""
    result = route_document(_uno())
    assert len(result["nets_routed"]) >= 21
    assert set(result["nets_poured"]) == {"GND", "+5V"}


# ------------------------------------------------- kicad-cli DRC ground truth


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not installed")
def test_uno_board_has_no_silk_or_hole_to_hole_warnings(tmp_path):
    """KiCad's own DRC on the routed, poured, through-hole Uno.

    Nothing here is filtered by severity: after both fixes the only violations
    KiCad reports are ``lib_footprint_*`` — bookkeeping that ForgeLab's
    synthesized footprints do not byte-match the installed KiCad libraries,
    which is a separate (and much larger) footprint-fidelity question.
    """
    doc = _uno()
    result = route_document(doc)
    board = tmp_path / "uno.kicad_pcb"
    board.write_bytes(KiCadExporter().from_ir(_routed(doc, result)))

    report = tmp_path / "drc.json"
    proc = subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            "--refill-zones",
            "--format",
            "json",
            "-o",
            str(report),
            str(board),
        ],  # fmt: skip
        capture_output=True,
        text=True,
        check=False,
    )
    assert report.exists(), proc.stderr
    violations = json.loads(report.read_text())["violations"]
    assert [v for v in violations if v["type"] == "silk_over_copper"] == []
    assert [v for v in violations if v["type"] == "hole_to_hole"] == []
    leftover = {v["type"] for v in violations if not v["type"].startswith("lib_footprint")}
    assert leftover == set(), sorted(leftover)


def test_via_and_pad_holes_keep_their_drill_wall():
    """Sanity on the geometry the ``hole_to_hole`` rule measures: no via hole is
    left overlapping a through-hole pad's hole on the routed Uno."""
    doc = _uno()
    result = route_document(doc)
    for via in result["vias"]:
        for _net, px, py, _w, _h in _through_hole_pads(doc):
            assert math.dist(via["at"], (px, py)) > via["drill"] / 2
