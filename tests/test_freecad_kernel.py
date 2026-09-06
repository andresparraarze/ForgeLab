"""The FreeCAD kernel bridge: framing, availability, and STEP normalization.

These tests deliberately need no FreeCAD. What they pin is the plumbing that
has to be right *before* the kernel is reachable: recovering a result from
FreeCAD's famously noisy stdout, refusing to pretend the kernel exists when it
does not, and stripping the wall-clock timestamp out of STEP output.

The geometry itself is exercised in ``test_geometry_verification.py``, which
skips without FreeCAD.
"""

import json

import pytest

from forgelab.formats import freecad_kernel as kernel
from forgelab.formats import step

# A faithful sample of what freecadcmd actually writes around a result: a
# banner, tab-separated progress percentages with no newlines between them, and
# a trailing cwd notice. Captured from a real run.
_NOISE_BEFORE = (
    "FreeCAD 1.1.3, Libs: 1.1.3R44987 (Git)\n"
    "(C) 2001-2026 FreeCAD contributors\n"
    "Importing project files......\n"
    "\t\t\t\t\tPostprocessing......\n"
    "\t\t\t(4 %)\t\t\t(9 %)\t\t\t(13 %)\t\t\t(100 %)"
)
_NOISE_AFTER = "\nShell cwd was reset to /home/user/project\n"


def _framed(payload: dict) -> str:
    return _NOISE_BEFORE + "@@FORGELAB@@" + json.dumps(payload) + "@@END@@" + _NOISE_AFTER


def test_result_survives_the_progress_noise_freecad_writes_around_it():
    """The whole point of the sentinel framing: stdout cannot be scraped."""
    payload = kernel.parse_result(_framed({"ok": True, "objects": [{"name": "Pad"}]}))
    assert payload == {"ok": True, "objects": [{"name": "Pad"}]}


def test_result_containing_percent_and_brace_text_still_parses():
    """Progress-like text *inside* the payload must not confuse the framing."""
    payload = kernel.parse_result(_framed({"ok": True, "note": "(50 %) {not json}"}))
    assert payload is not None
    assert payload["note"] == "(50 %) {not json}"


@pytest.mark.parametrize(
    "stdout",
    [
        "",  # script died before emitting anything
        _NOISE_BEFORE + _NOISE_AFTER,  # ran, but never reached _emit
        "@@FORGELAB@@not json at all@@END@@",  # truncated/garbled payload
        "@@FORGELAB@@[1, 2, 3]@@END@@",  # valid JSON, wrong shape
        '@@FORGELAB@@{"ok": true}',  # opening sentinel only
    ],
)
def test_unparseable_output_is_reported_as_no_result(stdout):
    """None, never a half-built dict — the caller turns this into a real error."""
    assert kernel.parse_result(stdout) is None


def test_availability_is_the_presence_of_freecadcmd(monkeypatch):
    monkeypatch.setattr(kernel.shutil, "which", lambda name: None)
    assert kernel.available() is False
    monkeypatch.setattr(kernel.shutil, "which", lambda name: "/usr/bin/freecadcmd")
    assert kernel.available() is True


def test_missing_freecad_raises_an_actionable_error(monkeypatch):
    """An optional dependency must say what to install, not fail obscurely."""
    monkeypatch.setattr(kernel.shutil, "which", lambda name: None)
    with pytest.raises(kernel.FreeCADKernelError) as excinfo:
        kernel.require_available()
    message = str(excinfo.value)
    assert "freecadcmd" in message
    assert "freecad.org" in message
    # The .FCStd exporter is pure stdlib; the error must not imply otherwise.
    assert "exporter itself needs no FreeCAD" in message


def test_every_kernel_entry_point_refuses_without_freecad(monkeypatch, tmp_path):
    monkeypatch.setattr(kernel.shutil, "which", lambda name: None)
    target = tmp_path / "part.FCStd"
    target.write_bytes(b"")
    for call in (
        lambda: kernel.inspect_document(target),
        lambda: kernel.tessellate(target),
        lambda: kernel.convert(target, tmp_path / "out.step", "step"),
    ):
        with pytest.raises(kernel.FreeCADKernelError):
            call()


def test_convert_rejects_an_unsupported_format(tmp_path):
    """Checked before the kernel is touched, so it fails the same way anywhere."""
    with pytest.raises(ValueError, match="fmt must be one of"):
        kernel.convert(tmp_path / "part.FCStd", tmp_path / "out.obj", "obj")


# --- STEP header normalization --------------------------------------------- #

_STEP = b"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('FreeCAD Model'),'2;1');
FILE_NAME('Open CASCADE Shape Model','2026-09-06T08:59:10',('FreeCAD'),(
    'FreeCAD'),'Open CASCADE STEP processor 7.9','FreeCAD','Unknown');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));
ENDSEC;
DATA;
#1 = APPLICATION_PROTOCOL_DEFINITION('','automotive_design',2000,#2);
ENDSEC;
END-ISO-10303-21;
"""


def test_normalize_replaces_the_wall_clock_timestamp():
    out = step.normalize(_STEP)
    assert b"2026-09-06T08:59:10" not in out
    assert step.FIXED_TIMESTAMP.encode() in out


def test_normalize_is_idempotent_and_stable():
    once = step.normalize(_STEP)
    assert step.normalize(once) == once


def test_normalize_leaves_everything_but_the_stamp_alone():
    out = step.normalize(_STEP)
    assert len(out) == len(_STEP)  # same-width ISO-8601 replacement
    for keep in (b"AUTOMOTIVE_DESIGN", b"Open CASCADE STEP processor 7.9", b"#1 = APPLICATION"):
        assert keep in out


def test_normalize_only_touches_the_header_section():
    """A timestamp-shaped string in DATA is content, not metadata."""
    data_stamp = _STEP.replace(
        b"#1 = APPLICATION_PROTOCOL_DEFINITION('','automotive_design',2000,#2);",
        b"#1 = DESCRIPTIVE_REPRESENTATION_ITEM('when','2026-09-06T08:59:10');",
    )
    out = step.normalize(data_stamp)
    assert out.count(b"2026-09-06T08:59:10") == 1  # the DATA one survives
    assert out.split(b"ENDSEC;")[0].count(b"2026-09-06T08:59:10") == 0


def test_normalize_passes_through_input_with_no_header():
    assert step.normalize(b"not a step file") == b"not a step file"
