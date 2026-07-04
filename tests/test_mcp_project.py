"""ForgeLab Project: create/load/update/export MCP tools, shared-dimension
inference, and informational cross-domain constraint reporting."""

import json

import pytest

from forgelab.mcp import tools
from forgelab.project import (
    Constraint,
    Project,
    check_constraints,
    dump_project,
    infer_shared,
)
from forgelab.spec import SPEC_VERSION


def _hardware_doc(width=68.58, height=53.34):
    """A minimal hardware document with a rectangular board outline."""
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "board", "generator": "test"},
        "nodes": [
            {
                "id": "board",
                "type": "board",
                "props": {
                    "kicad_version": "20221018",
                    "generator": "test",
                    "design_rules": {
                        "clearance": 0.2,
                        "track_width": 0.25,
                        "via_diameter": 0.8,
                        "via_drill": 0.4,
                    },
                    "outline": [
                        {"start": [0.0, 0.0], "end": [width, 0.0]},
                        {"start": [width, 0.0], "end": [width, height]},
                        {"start": [width, height], "end": [0.0, height]},
                        {"start": [0.0, height], "end": [0.0, 0.0]},
                    ],
                },
            },
            {
                "id": "R1",
                "type": "component",
                "props": {
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0402",
                    "layer": "F.Cu",
                    "at": [10.0, 10.0, 0.0],
                },
            },
        ],
    }


def _threed_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "threed",
        "meta": {"name": "render", "generator": "test"},
        "nodes": [{"id": "scene", "type": "scene", "props": {"name": "scene"}}],
    }


def _write(tmp_path, name, doc):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _output_dir(tmp_path, monkeypatch):
    """Point bare-filename resolution at an isolated temp output directory."""
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# shared-dimension inference
# --------------------------------------------------------------------------- #
def test_infer_shared_reads_board_outline_bounds():
    assert infer_shared(_hardware_doc(80.0, 40.0)) == {
        "board_width": 80.0,
        "board_height": 40.0,
    }


def test_infer_shared_ignores_non_hardware_documents():
    assert infer_shared(_threed_doc()) == {}


# --------------------------------------------------------------------------- #
# create_project
# --------------------------------------------------------------------------- #
def test_create_project_writes_file_and_infers_dimensions(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    out = tools.create_project("widget", "a demo product", ["board.forge.json"])

    project_path = tmp_path / "widget.forge.project"
    assert out["project_path"] == str(project_path)
    assert project_path.exists()
    assert out["documents"] == {"board": "board.forge.json"}
    # board_width/board_height inferred from the hardware board outline.
    assert out["shared"] == {"board_width": 68.58, "board_height": 53.34}

    on_disk = json.loads(project_path.read_text(encoding="utf-8"))
    assert on_disk["name"] == "widget"
    assert on_disk["description"] == "a demo product"
    assert on_disk["forgelab_version"] == SPEC_VERSION


def test_create_project_without_documents_has_empty_shared(tmp_path):
    out = tools.create_project("empty")
    assert out["documents"] == {}
    assert out["shared"] == {}
    assert (tmp_path / "empty.forge.project").exists()


def test_create_project_requires_a_name():
    with pytest.raises(ValueError, match="name is required"):
        tools.create_project("")


# --------------------------------------------------------------------------- #
# load_project
# --------------------------------------------------------------------------- #
def test_load_project_summarizes_each_document(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    _write(tmp_path, "render.forge.json", _threed_doc())
    tools.create_project("widget", "", ["board.forge.json", "render.forge.json"])

    out = tools.load_project("widget.forge.project")
    assert out["name"] == "widget"
    assert out["shared"] == {"board_width": 68.58, "board_height": 53.34}
    summaries = {d["key"]: d for d in out["documents"]}
    assert summaries["board"]["domain"] == "hardware"
    assert summaries["board"]["valid"] is True
    assert summaries["board"]["node_count"] == 2
    assert summaries["render"]["domain"] == "threed"
    assert summaries["render"]["valid"] is True


def test_load_project_flags_an_invalid_linked_document(tmp_path):
    _write(tmp_path, "broken.forge.json", {"domain": "hardware", "nodes": "not-a-list"})
    tools.create_project("widget", "", [])
    # Manually link a broken document (create_project would reject it on read).
    project_path = tmp_path / "widget.forge.project"
    data = json.loads(project_path.read_text(encoding="utf-8"))
    data["documents"] = {"broken": "broken.forge.json"}
    project_path.write_text(json.dumps(data), encoding="utf-8")

    out = tools.load_project("widget.forge.project")
    broken = out["documents"][0]
    assert broken["valid"] is False
    assert "error" in broken


# --------------------------------------------------------------------------- #
# update_project
# --------------------------------------------------------------------------- #
def test_update_project_changes_shared_dimensions(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    tools.create_project("widget", "", ["board.forge.json"])

    out = tools.update_project("widget.forge.project", {"board_width": 70.0, "mounting": 3.2})
    assert out["shared"]["board_width"] == 70.0
    assert out["shared"]["mounting"] == 3.2
    assert out["shared"]["board_height"] == 53.34  # untouched
    assert out["updated"] == ["board_width", "mounting"]

    # Persisted to disk.
    on_disk = json.loads((tmp_path / "widget.forge.project").read_text(encoding="utf-8"))
    assert on_disk["shared"]["board_width"] == 70.0


def test_update_project_revalidate_reports_constraints(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    tools.create_project("widget", "", ["board.forge.json"])
    out = tools.update_project("widget.forge.project", {"board_width": 70.0}, revalidate=True)
    assert out["validation"] == [{"key": "board", "valid": True}]
    assert out["constraints"] == []
    assert out["violations"] == []


def test_update_project_rejects_empty_shared():
    with pytest.raises(ValueError, match="non-empty dict"):
        tools.update_project("anything.forge.project", {})


# --------------------------------------------------------------------------- #
# export_project
# --------------------------------------------------------------------------- #
def test_export_project_exports_every_document(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    _write(tmp_path, "render.forge.json", _threed_doc())
    tools.create_project("widget", "", ["board.forge.json", "render.forge.json"])

    out = tools.export_project("widget.forge.project")
    assert out["exported_count"] == 2
    by_doc = {e["document"]: e for e in out["exported"]}
    # Default tool per domain: hardware -> kicad, threed -> gltf.
    assert by_doc["board"]["tool"] == "kicad"
    assert by_doc["board"]["exported"] is True
    assert by_doc["board"]["path"].endswith("board.kicad_pcb")
    assert by_doc["render"]["tool"] == "gltf"
    assert by_doc["render"]["path"].endswith("render.gltf")
    # The files were actually written.
    assert (tmp_path / "board.kicad_pcb").exists()
    assert (tmp_path / "render.gltf").exists()


def test_export_project_honors_per_document_tool_override(tmp_path):
    _write(tmp_path, "render.forge.json", _threed_doc())
    tools.create_project("widget", "", ["render.forge.json"])

    out = tools.export_project("widget.forge.project", tools={"render": "blender_script"})
    entry = out["exported"][0]
    assert entry["tool"] == "blender_script"
    assert entry["path"].endswith("render.py")
    assert (tmp_path / "render.py").exists()


# --------------------------------------------------------------------------- #
# constraint violation reporting (informational; never blocks)
# --------------------------------------------------------------------------- #
def test_constraint_violation_is_reported_on_export(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    tools.create_project("widget", "", ["board.forge.json"])

    # Add a constraint: a board component's X must be at least board_width + 2mm.
    # The component sits at x=10, far below 68.58 + 2, so this must report a
    # violation — but the export still succeeds (informational only).
    project_path = tmp_path / "widget.forge.project"
    data = json.loads(project_path.read_text(encoding="utf-8"))
    data["constraints"] = [
        {
            "description": "component x must clear the board width",
            "type": "min_value",
            "source": "shared.board_width",
            "target_document": "board",
            "target_path": "/nodes/1/props/at/0",
            "offset": 2.0,
        }
    ]
    project_path.write_text(json.dumps(data), encoding="utf-8")

    out = tools.export_project("widget.forge.project")
    assert out["exported_count"] == 1  # export not blocked
    assert len(out["violations"]) == 1
    violation = out["violations"][0]
    assert violation["satisfied"] is False
    assert violation["expected"] == pytest.approx(70.58)
    assert violation["actual"] == pytest.approx(10.0)
    assert "message" in violation


def test_check_constraints_satisfied_when_target_meets_minimum():
    project = Project(
        name="p",
        shared={"board_width": 68.58},
        constraints=[
            Constraint(
                source="shared.board_width",
                target_document="enc",
                target_path="/inner_width",
                offset=2.0,
            )
        ],
    )
    docs = {"enc": {"inner_width": 71.0}}  # 71.0 >= 68.58 + 2.0
    reports = check_constraints(project, docs)
    assert reports[0]["satisfied"] is True


def test_dump_project_round_trips_through_parse(tmp_path):
    project = Project(name="p", shared={"w": 1.0}, documents={"a": "a.forge.json"})
    text = dump_project(project)
    reloaded = json.loads(text)
    assert reloaded["name"] == "p"
    assert reloaded["shared"] == {"w": 1.0}
    assert text.endswith("\n")


def test_load_project_rejects_malformed_project_with_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    bad = tmp_path / "bad.forge.project"
    bad.write_text(json.dumps({"name": "p", "unexpected_key": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid ForgeLab project"):
        tools.load_project("bad.forge.project")
