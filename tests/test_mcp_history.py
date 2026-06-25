"""Design history: .forge.history recording + get_history / get_project_summary."""

import json

import pytest

from forgelab import history
from forgelab.history import HISTORY_FILENAME, MAX_ENTRIES
from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION


def _hardware_doc():
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
                        {"start": [0.0, 0.0], "end": [10.0, 0.0]},
                        {"start": [10.0, 0.0], "end": [10.0, 10.0]},
                        {"start": [10.0, 10.0], "end": [0.0, 10.0]},
                        {"start": [0.0, 10.0], "end": [0.0, 0.0]},
                    ],
                },
            },
            {"id": "net1", "type": "net", "props": {"code": 1, "name": "GND"}},
            {
                "id": "R1",
                "type": "component",
                "props": {
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805_2012Metric",
                    "layer": "F.Cu",
                    "at": [1.0, 1.0, 0.0],
                    "pads": [{"number": "1", "net": "GND"}],
                },
            },
        ],
    }


def _write(tmp_path, name, doc):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# history file is created on write
# --------------------------------------------------------------------------- #
def test_patch_document_creates_history(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    history_file = tmp_path / HISTORY_FILENAME
    assert not history_file.exists()

    tools.patch_document(
        "board.forge.json", [{"op": "replace", "path": "/meta/name", "value": "X"}]
    )

    assert history_file.exists()
    entries = json.loads(history_file.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["tool"] == "patch_document"
    assert entries[0]["operations"] == 1
    assert "timestamp" in entries[0]


def test_export_document_creates_history(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    tools.export_document(
        document_path="board.forge.json", tool="kicad", output_path="board.kicad_pcb"
    )
    entries = json.loads((tmp_path / HISTORY_FILENAME).read_text(encoding="utf-8"))
    assert entries[-1]["tool"] == "export_document"
    assert entries[-1]["output_tool"] == "kicad"
    assert entries[-1]["bytes_written"] > 0
    assert entries[-1]["output_path"].endswith("board.kicad_pcb")


def test_export_document_inline_does_not_record(tmp_path):
    # No output_path => nothing written to disk => no history entry.
    tools.export_document(document=_hardware_doc(), tool="kicad")
    assert not (tmp_path / HISTORY_FILENAME).exists()


# --------------------------------------------------------------------------- #
# get_history
# --------------------------------------------------------------------------- #
def test_get_history_returns_entries(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    tools.patch_document(
        "board.forge.json", [{"op": "replace", "path": "/meta/name", "value": "A"}]
    )
    tools.export_document(
        document_path="board.forge.json", tool="kicad", output_path="board.kicad_pcb"
    )

    out = tools.get_history("board.forge.json")
    assert [e["tool"] for e in out] == ["patch_document", "export_document"]
    assert all("timestamp" in e and "summary" in e for e in out)
    assert "patched" in out[0]["summary"]
    assert "exported" in out[1]["summary"]


def test_get_history_missing_file_is_empty(tmp_path):
    # A directory with no .forge.history yields an empty list, not an error.
    assert tools.get_history("nonexistent.forge.json") == []


def test_get_history_returns_only_last_20(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    for i in range(25):
        tools.patch_document(
            "board.forge.json", [{"op": "replace", "path": "/meta/name", "value": f"n{i}"}]
        )
    out = tools.get_history("board.forge.json")
    assert len(out) == 20  # capped at the last 20


# --------------------------------------------------------------------------- #
# get_project_summary
# --------------------------------------------------------------------------- #
def test_get_project_summary_counts(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    tools.create_project("widget", "demo", ["board.forge.json"])
    tools.update_project("widget.forge.project", {"board_width": 70.0})
    tools.export_project("widget.forge.project", tools={"board": "kicad"})

    summary = tools.get_project_summary("widget.forge.project")
    assert summary["name"] == "widget"
    assert summary["description"] == "demo"
    assert "board" in summary["documents"]
    assert summary["shared"]["board_width"] == 70.0
    # update_project + export_project = 2 total changes; 1 of them an export.
    assert summary["total_changes"] == 2
    assert summary["export_count"] == 1
    assert summary["last_modified"] is not None
    assert "widget" in summary["summary"]


def test_get_project_summary_without_history(tmp_path):
    _write(tmp_path, "board.forge.json", _hardware_doc())
    tools.create_project("widget", "", ["board.forge.json"])
    # No writes yet beyond create_project (which does not record history).
    summary = tools.get_project_summary("widget.forge.project")
    assert summary["total_changes"] == 0
    assert summary["export_count"] == 0
    # Falls back to the project file's mtime rather than None.
    assert summary["last_modified"] is not None


# --------------------------------------------------------------------------- #
# 100-entry trim (newest kept)
# --------------------------------------------------------------------------- #
def test_history_trims_to_max_entries(tmp_path):
    doc = tmp_path / "board.forge.json"
    doc.write_text("{}", encoding="utf-8")
    for i in range(MAX_ENTRIES + 5):
        history.record(doc, {"tool": "patch_document", "document_path": str(doc), "seq": i})

    entries = json.loads((tmp_path / HISTORY_FILENAME).read_text(encoding="utf-8"))
    assert len(entries) == MAX_ENTRIES
    # Oldest trimmed, newest kept (entries 5..104 of 0..104).
    assert entries[0]["seq"] == 5
    assert entries[-1]["seq"] == MAX_ENTRIES + 4


def test_record_never_raises_on_bad_path(tmp_path):
    # A path whose parent cannot be created must not raise (best-effort).
    bad = tmp_path / "board.forge.json"
    bad.write_text("{}", encoding="utf-8")
    # Corrupt the history file; record should overwrite, not crash.
    (tmp_path / HISTORY_FILENAME).write_text("not json", encoding="utf-8")
    history.record(bad, {"tool": "patch_document"})
    entries = json.loads((tmp_path / HISTORY_FILENAME).read_text(encoding="utf-8"))
    assert len(entries) == 1
