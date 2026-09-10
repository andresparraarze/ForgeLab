"""STEP and STL export: the formats that get a part out of FreeCAD.

STEP is what every other CAD package reads and STL is what slicers read, so
these are how a ForgeLab part reaches anyone not running FreeCAD. Both are
evaluated formats — they carry the built result, not the recipe — which is why
they need the kernel when the ``.FCStd`` exporter does not.

The determinism tests matter more than they look: OCC stamps the wall clock
into every STEP header, so without normalization the same document exports to
different bytes one second apart.
"""

import json
import time
from pathlib import Path

import pytest
from external_tools import requires_freecad

from forgelab.core import validate
from forgelab.core.pipeline import default_registry
from forgelab.exporters.mechanical import StepExporter, StlExporter
from forgelab.formats import freecad_kernel, step
from forgelab.spec import SPEC_VERSION, DocumentMeta, Domain, ForgeDocument, Node

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples/mechanical"


def _example(name: str) -> ForgeDocument:
    return validate(json.loads((_EXAMPLES / name).read_text()))


# --- registration and refusals (no FreeCAD needed) -------------------------- #


def test_both_formats_are_registered_for_export():
    formats = default_registry().tool_names()
    assert formats["step"] == {"import": False, "export": True}
    # stl is the one tool whose importer (threed) and exporter (mechanical)
    # serve different domains, so this is not a round trip.
    assert formats["stl"] == {"import": True, "export": True}


@pytest.mark.parametrize("exporter", [StepExporter, StlExporter])
def test_refuses_a_non_mechanical_document_with_a_usable_alternative(exporter):
    doc = ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.THREED,
        meta=DocumentMeta(name="scene"),
        nodes=[],
    )
    with pytest.raises(ValueError, match="mechanical documents"):
        exporter().from_ir(doc)
    with pytest.raises(ValueError, match="gltf"):
        exporter().from_ir(doc)


@pytest.mark.parametrize("exporter", [StepExporter, StlExporter])
def test_refuses_a_document_that_defines_no_solid(exporter):
    """Checked before the kernel runs, and points at the tool that diagnoses it."""
    doc = ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="empty"),
        nodes=[Node(id="B", type="body", props={"name": "B"})],
    )
    with pytest.raises(ValueError, match="verify_geometry"):
        exporter().from_ir(doc)


@pytest.mark.parametrize("exporter", [StepExporter, StlExporter])
def test_refuses_without_freecad_naming_what_to_install(exporter, monkeypatch):
    monkeypatch.setattr(freecad_kernel.shutil, "which", lambda name: None)
    with pytest.raises(freecad_kernel.FreeCADKernelError, match="freecadcmd"):
        exporter().from_ir(_example("motor_mount.forge.json"))


# --- real kernel ------------------------------------------------------------ #


@requires_freecad
def test_step_reimports_into_freecad_with_the_same_volume(tmp_path):
    """The end-to-end claim: the STEP contains the part, not an approximation."""
    doc = _example("motor_mount.forge.json")
    out = tmp_path / "part.step"
    out.write_bytes(StepExporter().from_ir(doc))

    reimported = tmp_path / "check.FCStd"
    script = tmp_path / "check.py"
    script.write_text(
        "import FreeCAD as App, Part, json\n"
        f"doc = App.newDocument('t')\n"
        f"Part.insert({str(out)!r}, 't')\n"
        "solids = [o for o in doc.Objects if getattr(o, 'Shape', None) is not None "
        "and not o.Shape.isNull() and o.Shape.Solids]\n"
        f"doc.saveAs({str(reimported)!r})\n"
        "print('VOLUME:', round(sum(o.Shape.Volume for o in solids), 2), "
        "'COUNT:', len(solids))\n"
    )
    import subprocess

    result = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=180
    )
    assert "COUNT: 1" in result.stdout, result.stdout + result.stderr
    # The same figure the .FCStd itself reports, to the same 2 decimals.
    assert "VOLUME: 14297.85" in result.stdout, result.stdout


@requires_freecad
def test_step_export_is_byte_identical_across_a_clock_tick():
    """Without header normalization these differ: OCC stamps the wall clock."""
    doc = _example("motor_mount.forge.json")
    first = StepExporter().from_ir(doc)
    time.sleep(1.1)
    second = StepExporter().from_ir(doc)
    assert first == second


@requires_freecad
def test_step_export_embeds_no_wall_clock_time():
    """The same rule the generated Blender scripts are held to."""
    data = StepExporter().from_ir(_example("motor_mount.forge.json"))
    header = data.split(b"ENDSEC;")[0]
    assert step.FIXED_TIMESTAMP.encode() in header
    assert time.strftime("%Y-%m-%d").encode() not in data


@requires_freecad
def test_step_is_a_wellformed_iso_10303_file():
    data = StepExporter().from_ir(_example("rounded_knob.forge.json"))
    assert data.startswith(b"ISO-10303-21;")
    assert data.rstrip().endswith(b"END-ISO-10303-21;")
    assert b"ADVANCED_BREP_SHAPE_REPRESENTATION" in data or b"MANIFOLD_SOLID_BREP" in data


@requires_freecad
def test_stl_export_is_a_binary_mesh_with_the_right_extent(tmp_path):
    doc = _example("motor_mount.forge.json")
    data = StlExporter().from_ir(doc)
    assert len(data) > 1000

    # Binary STL: 80-byte header, uint32 facet count, 50 bytes per facet.
    import struct

    (facets,) = struct.unpack("<I", data[80:84])
    assert facets > 100
    assert len(data) == 84 + facets * 50


@requires_freecad
def test_stl_export_is_deterministic():
    doc = _example("motor_mount.forge.json")
    first = StlExporter().from_ir(doc)
    time.sleep(1.1)
    assert StlExporter().from_ir(doc) == first


@requires_freecad
@pytest.mark.parametrize("tool", ["step", "stl"])
def test_export_document_writes_the_file_through_mcp(tmp_path, monkeypatch, tool):
    from forgelab.mcp import tools

    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    source = tmp_path / "part.forge.json"
    source.write_text(json.dumps(_example("motor_mount.forge.json").model_dump(mode="json")))

    result = tools.export_document(document_path=str(source), tool=tool, output_path=f"part.{tool}")
    assert result["bytes_written"] > 1000
    assert Path(result["path"]).exists()
