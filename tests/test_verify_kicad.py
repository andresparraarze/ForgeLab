"""KiCad's own DRC, reachable from ForgeLab rather than only from the tests.

The mechanical domain has always been able to ask the real kernel whether a part
built. Hardware could not ask KiCad anything: `tests/external_tools.py` says a
board is checked by running kicad-cli's DRC, but that only happened in three
tests, and nothing in `forgelab/` ever shelled out to it. An agent could build,
place, route and fab-check a board and never learn that KiCad rejected it.
"""

import json
from pathlib import Path

import pytest
from external_tools import requires_kicad_cli

from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION, ForgeDocument
from forgelab.verify import VerifyError, kicad

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _board(nodes: list[dict]) -> ForgeDocument:
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "drc", "generator": "test"},
            "nodes": [
                {
                    "id": "board",
                    "type": "board",
                    "props": {
                        "kicad_version": "20240108",
                        "generator": "pcbnew",
                        "layers": [
                            {"ordinal": 0, "canonical_name": "F.Cu", "layer_type": "signal"},
                            {"ordinal": 31, "canonical_name": "B.Cu", "layer_type": "signal"},
                            {"ordinal": 44, "canonical_name": "Edge.Cuts", "layer_type": "user"},
                        ],
                        "outline": [
                            {"start": [0, 0], "end": [30, 0]},
                            {"start": [30, 0], "end": [30, 20]},
                            {"start": [30, 20], "end": [0, 20]},
                            {"start": [0, 20], "end": [0, 0]},
                        ],
                        "design_rules": {
                            "clearance": 0.2,
                            "track_width": 0.25,
                            "via_diameter": 0.8,
                            "via_drill": 0.4,
                        },
                    },
                },
                *nodes,
            ],
        }
    )


def test_a_non_hardware_document_is_refused_clearly():
    """It used to fail deep inside the FreeCAD exporter instead."""
    doc = ForgeDocument.model_validate(
        json.loads((_EXAMPLES / "mechanical/box-with-hole.forge.json").read_text())
    )
    with pytest.raises(VerifyError, match="hardware documents"):
        kicad.verify_document(doc)


def test_generation_status_reports_whether_kicad_is_installed():
    """An agent has to be able to discover the capability before relying on it."""
    status = tools.generation_status()
    assert status["kicad_cli"] == kicad.available()
    if not status["kicad_cli"]:
        assert "kicad_reason" in status


@pytest.mark.skipif(kicad.available(), reason="KiCad is installed here")
def test_without_kicad_the_message_says_what_to_install():
    with pytest.raises(VerifyError, match="kicad-cli"):
        kicad.verify_document(_board([]))


@requires_kicad_cli
def test_a_clean_board_verifies():
    """blinky, routed by hand: one track joining the only two-pad net."""
    doc = _board(
        [
            {"id": "net:1", "type": "net", "props": {"code": 1, "name": "SIG"}},
            {
                "id": "R1",
                "type": "component",
                "props": {
                    "reference": "R1",
                    "value": "1k",
                    "footprint": "Resistor_SMD:R_0603_1608Metric",
                    "layer": "F.Cu",
                    "at": [10, 10, 0],
                    "pads": [{"number": "1", "net": "SIG"}, {"number": "2", "net": ""}],
                },
            },
        ]
    )
    result = kicad.verify_document(doc)
    assert result["verified"] is True, result["errors"]
    assert result["errors"] == []
    assert result["checked_by"].startswith("kicad-cli")


@requires_kicad_cli
def test_an_unrouted_net_is_reported_as_unconnected():
    """The check ForgeLab's own connectivity model exists alongside, not instead of."""
    doc = _board(
        [
            {"id": "net:1", "type": "net", "props": {"code": 1, "name": "SIG"}},
            {
                "id": "R1",
                "type": "component",
                "props": {
                    "reference": "R1",
                    "value": "1k",
                    "footprint": "Resistor_SMD:R_0603_1608Metric",
                    "layer": "F.Cu",
                    "at": [8, 10, 0],
                    "pads": [{"number": "1", "net": "SIG"}, {"number": "2", "net": ""}],
                },
            },  # fmt: skip
            {
                "id": "R2",
                "type": "component",
                "props": {
                    "reference": "R2",
                    "value": "1k",
                    "footprint": "Resistor_SMD:R_0603_1608Metric",
                    "layer": "F.Cu",
                    "at": [22, 10, 0],
                    "pads": [{"number": "1", "net": "SIG"}, {"number": "2", "net": ""}],
                },
            },  # fmt: skip
        ]
    )
    result = kicad.verify_document(doc)
    assert result["verified"] is False
    assert result["unconnected"] >= 1
    assert any("unconnected" in e for e in result["errors"])


@requires_kicad_cli
def test_verify_geometry_dispatches_on_domain(tmp_path):
    """One tool, two authorities — FreeCAD for parts, KiCad for boards."""
    board = tmp_path / "b.forge.json"
    board.write_text((_EXAMPLES / "hardware/blinky.forge.json").read_text())
    result = tools.verify_geometry(document_path=str(board))
    assert result["checked_by"].startswith("kicad-cli")
    assert "unconnected" in result


@requires_kicad_cli
def test_kicad_sees_what_forgelabs_own_checks_cannot(tmp_path):
    """The reason this exists: a board can pass every ForgeLab check and fail KiCad.

    Two TQFP-32s 10.0mm apart. Their copper spans 9.8mm, so the nearest pads are
    0.2mm clear and every ForgeLab clearance rule is satisfied. Their courtyards
    span 10.3mm, so the packages physically collide — a rule ForgeLab has no
    concept of, because a courtyard is not copper.
    """
    from forgelab.validation import check_fab_rules

    def part(ref: str, x: float) -> dict:
        return {
            "id": ref,
            "type": "component",
            "props": {
                "reference": ref, "value": "U",
                "footprint": "Package_QFP:TQFP-32_7x7mm_P0.8mm",
                "layer": "F.Cu", "at": [x, 10, 0],
                "pads": [{"number": str(n), "net": ""} for n in range(1, 33)],
            },
        }  # fmt: skip

    doc = _board([part("U1", 9.0), part("U2", 19.0)])
    assert check_fab_rules(doc)["passed"] is True, "no copper rule is broken"
    result = kicad.verify_document(doc)
    assert any("courtyards_overlap" in e for e in result["errors"]), result["errors"]
