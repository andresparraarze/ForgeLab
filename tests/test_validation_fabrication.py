"""Fabrication rule checks (forgelab.validation.fabrication) + MCP tools."""

import json

import pytest

from forgelab.core import validate
from forgelab.mcp import tools
from forgelab.spec.version import SPEC_VERSION
from forgelab.validation import check_fab_rules


def _rect_outline(width, height):
    return [
        {"start": [0.0, 0.0], "end": [width, 0.0]},
        {"start": [width, 0.0], "end": [width, height]},
        {"start": [width, height], "end": [0.0, height]},
        {"start": [0.0, height], "end": [0.0, 0.0]},
    ]


def _doc(
    track_width=0.25,
    via_diameter=0.8,
    via_drill=0.4,
    width=68.58,
    height=53.34,
    domain="hardware",
    drill_size=None,
):
    design_rules = {
        "clearance": 0.2,
        "track_width": track_width,
        "via_diameter": via_diameter,
        "via_drill": via_drill,
    }
    if drill_size is not None:
        design_rules["drill_size"] = drill_size
    return validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": domain,
            "meta": {"name": "t", "generator": "test", "description": None},
            "nodes": [
                {
                    "id": "board",
                    "type": "board",
                    "props": {
                        "kicad_version": "20221018",
                        "generator": "forgelab",
                        "outline": _rect_outline(width, height),
                        "design_rules": design_rules,
                    },
                },
                {"id": "net1", "type": "net", "props": {"code": 1, "name": "GND"}},
            ],
        }
    )


def _threed_doc():
    return validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "threed",
            "meta": {"name": "s", "generator": "test", "description": None},
            "nodes": [{"id": "s", "type": "scene", "props": {"name": "s"}}],
        }
    )


# --------------------------------------------------------------------------- #
# check_fab_rules
# --------------------------------------------------------------------------- #
def test_jlcpcb_pass():
    result = check_fab_rules(_doc(), "jlcpcb")
    assert result == {"fab": "jlcpcb", "passed": True, "errors": [], "warnings": []}


def test_jlcpcb_fail_on_trace_width():
    result = check_fab_rules(_doc(track_width=0.05), "jlcpcb")
    assert result["passed"] is False
    assert any("trace width" in e for e in result["errors"])


def test_jlcpcb_fail_on_via_geometry():
    result = check_fab_rules(_doc(via_diameter=0.3, via_drill=0.1), "jlcpcb")
    assert result["passed"] is False
    assert any("via diameter" in e for e in result["errors"])
    assert any("via drill" in e for e in result["errors"])


def test_jlcpcb_fail_on_board_too_large():
    result = check_fab_rules(_doc(width=600.0, height=600.0), "jlcpcb")
    assert result["passed"] is False
    assert any("exceeds jlcpcb maximum" in e for e in result["errors"])


def test_jlcpcb_fail_on_board_too_small():
    result = check_fab_rules(_doc(width=3.0, height=3.0), "jlcpcb")
    assert result["passed"] is False
    assert any("below jlcpcb minimum" in e for e in result["errors"])


def test_pcbway_allows_larger_board_than_jlcpcb():
    # 600x600 exceeds JLCPCB's 500 limit but is within PCBWay's 600.
    big = _doc(width=600.0, height=600.0)
    assert check_fab_rules(big, "jlcpcb")["passed"] is False
    assert check_fab_rules(big, "pcbway")["passed"] is True


def test_oshpark_has_no_board_size_limit():
    # OSH Park profile defines no board-size envelope, so a huge board passes.
    result = check_fab_rules(_doc(width=1000.0, height=1000.0), "oshpark")
    assert result["passed"] is True


def test_drill_size_pass_when_at_or_above_minimum():
    # 0.3mm >= JLCPCB's 0.2mm minimum drill size.
    assert check_fab_rules(_doc(drill_size=0.3), "jlcpcb")["passed"] is True


def test_drill_size_fail_below_minimum():
    result = check_fab_rules(_doc(drill_size=0.15), "jlcpcb")
    assert result["passed"] is False
    assert any("drill size" in e for e in result["errors"])


def test_drill_size_absent_is_not_checked():
    # No drill_size in the document => the optional check is skipped, board passes.
    result = check_fab_rules(_doc(), "jlcpcb")
    assert result["passed"] is True
    assert not any("drill size" in e for e in result["errors"])


def test_drill_size_ignored_by_profile_without_limit():
    # OSH Park profile has no min_drill_size, so even a tiny drill passes.
    assert check_fab_rules(_doc(drill_size=0.05), "oshpark")["passed"] is True


def test_unknown_fab_raises():
    with pytest.raises(ValueError, match="unknown fab"):
        check_fab_rules(_doc(), "not-a-fab")


# --------------------------------------------------------------------------- #
# domain gating
# --------------------------------------------------------------------------- #
def test_non_hardware_returns_empty():
    result = check_fab_rules(_threed_doc(), "jlcpcb")
    assert result == {"fab": "jlcpcb", "passed": True, "errors": [], "warnings": []}


# --------------------------------------------------------------------------- #
# MCP tools
# --------------------------------------------------------------------------- #
def test_list_fab_profiles():
    profiles = tools.list_fab_profiles()
    assert set(profiles) == {"jlcpcb", "pcbway", "oshpark"}
    assert profiles["jlcpcb"]["min_trace_width"] == 0.1
    assert profiles["jlcpcb"]["max_board_width"] == 500.0
    assert profiles["pcbway"]["max_board_width"] == 600.0
    assert profiles["oshpark"]["min_via_diameter"] == 0.406
    # Returned table is a copy: mutating it does not corrupt the source.
    profiles["jlcpcb"]["min_trace_width"] = 99.0
    assert tools.list_fab_profiles()["jlcpcb"]["min_trace_width"] == 0.1


def test_check_fabrication_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    (tmp_path / "b.forge.json").write_text(
        json.dumps(_doc(track_width=0.05).model_dump(mode="json")), encoding="utf-8"
    )
    result = tools.check_fabrication("b.forge.json", fab="jlcpcb")
    assert result["fab"] == "jlcpcb"
    assert result["passed"] is False
    assert any("trace width" in e for e in result["errors"])


# --------------------------------------------------------------------------- #
# validate_document surfaces fab violations as warnings (never errors)
# --------------------------------------------------------------------------- #
def test_validate_document_includes_fab_warnings():
    doc = _doc(track_width=0.05).model_dump(mode="json")
    result = tools.validate_document(document=doc)
    assert result["valid"] is True  # fab issues are warnings, not errors
    assert any("fab(jlcpcb)" in w and "trace width" in w for w in result["warnings"])


def test_validate_document_clean_board_has_no_fab_warnings():
    doc = _doc().model_dump(mode="json")
    result = tools.validate_document(document=doc)
    assert result["valid"] is True
    assert not any("fab(" in w for w in result.get("warnings", []))


def test_check_gerber_completeness_tool(tmp_path, monkeypatch):
    # The pre-flight is exposed as an MCP tool so agents can call it before
    # export_document(tool='gerber'), not just as a library function.
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    (tmp_path / "b.forge.json").write_text(
        json.dumps(_doc().model_dump(mode="json")), encoding="utf-8"
    )
    result = tools.check_gerber_completeness("b.forge.json")
    assert result["fab"] == "jlcpcb"
    assert result["ready"] is True
    assert any("no routed tracks" in w for w in result["warnings"])

    (tmp_path / "bad.forge.json").write_text(
        json.dumps(_doc(track_width=0.05).model_dump(mode="json")), encoding="utf-8"
    )
    bad = tools.check_gerber_completeness("bad.forge.json", fab="jlcpcb")
    assert bad["ready"] is False
    assert any("trace width" in e for e in bad["errors"])
