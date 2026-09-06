"""Every FreeCAD-dependent entry point must fail the same way without FreeCAD.

This is the test that would have caught the bug that broke CI on 2026-09-06.
``preview_render`` let ``FreeCADKernelError`` escape, and because that class was
the only user-facing error in the codebase not derived from ``ValueError``, the
tool asserting ``pytest.raises(ValueError)`` passed on this dev box — which has
FreeCAD — and failed on all four CI interpreters, which do not.

So these tests never ask the machine whether FreeCAD is installed. They hide it
and assert the contract directly, which means they run identically everywhere:
an entry point that needs a kernel it cannot find raises ``ValueError`` naming
``freecadcmd``, whatever layer the failure originated in.
"""

import json
import shutil
from pathlib import Path

import pytest

from forgelab.core import validate
from forgelab.exporters.mechanical.step import StepExporter, StlExporter
from forgelab.mcp import tools
from forgelab.preview import render_preview
from forgelab.verify import verify_document

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples/mechanical/motor_mount.forge.json"


@pytest.fixture
def no_freecad(monkeypatch):
    """Hide freecadcmd from every lookup, leaving other executables alone."""
    real = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name, *a, **k: None if name == "freecadcmd" else real(name, *a, **k)
    )


@pytest.fixture
def part(tmp_path):
    """The motor mount, on disk and parsed — the path-taking tools need both."""
    target = tmp_path / "part.forge.json"
    target.write_bytes(_EXAMPLE.read_bytes())
    return target


def _document():
    return validate(json.loads(_EXAMPLE.read_text()))


# --- the MCP surface -------------------------------------------------------- #


def _mcp_entry_points(part, tmp_path):
    """Every MCP tool that can reach the kernel, as callables."""
    doc = json.loads(_EXAMPLE.read_text())
    return {
        "verify_geometry": lambda: tools.verify_geometry(str(part)),
        "preview_render": lambda: tools.preview_render(
            document_path=str(part), output_path=str(tmp_path / "preview.png")
        ),
        "export_document(step)": lambda: tools.export_document(document=doc, tool="step"),
        "export_document(stl)": lambda: tools.export_document(document=doc, tool="stl"),
    }


@pytest.mark.parametrize("name", sorted(_mcp_entry_points(Path("x"), Path("y"))))
def test_mcp_tools_report_a_missing_kernel_as_value_error(name, no_freecad, part, tmp_path):
    """An MCP tool's failures are ValueErrors — a missing kernel included.

    ``export_document`` is the one that was still broken after the first fix:
    it catches NotImplementedError, ValidationError and ValueError from the
    exporter, and a RuntimeError went straight past all three.
    """
    with pytest.raises(ValueError) as excinfo:
        _mcp_entry_points(part, tmp_path)[name]()
    assert "freecadcmd" in str(excinfo.value), f"{name} did not say what to install"


# --- the library surface underneath ----------------------------------------- #


@pytest.mark.parametrize(
    "name,call",
    [
        ("verify_document", lambda doc, out: verify_document(doc)),
        ("render_preview", lambda doc, out: render_preview(doc, str(out))),
        ("StepExporter", lambda doc, out: StepExporter().from_ir(doc)),
        ("StlExporter", lambda doc, out: StlExporter().from_ir(doc)),
    ],
)
def test_library_entry_points_raise_value_error_too(name, call, no_freecad, tmp_path):
    """The contract holds one layer down, so a new MCP tool inherits it.

    Enforcing this only at the MCP boundary would leave the next caller of
    ``verify_document`` or an exporter to rediscover the problem.
    """
    with pytest.raises(ValueError) as excinfo:
        call(_document(), tmp_path / "preview.png")
    assert "freecadcmd" in str(excinfo.value)


def test_the_kernel_error_is_a_value_error():
    """Pinning the reason the above holds, so it cannot be undone by accident.

    Every error class in forgelab/formats/ derives from ValueError — FcstdError,
    SExprError, GltfError — and so does every service error (PreviewError,
    VerifyError, PatchError). FreeCADKernelError deriving from RuntimeError made
    it the single exception to that rule and cost a red build.
    """
    from forgelab.formats import FreeCADKernelError

    assert issubclass(FreeCADKernelError, ValueError)
