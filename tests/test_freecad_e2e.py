"""End-to-end FreeCAD validation: exported FCStd genuinely opens in FreeCAD.

Runs only where FreeCAD is installed (``freecadcmd`` on PATH); skipped in CI.
"""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("freecadcmd") is None, reason="FreeCAD is not installed"
)

_CHECK = textwrap.dedent(
    """
    import FreeCAD as App
    doc = App.openDocument({path!r})
    n = doc.recompute()  # plain recompute, no touch() — live-testing semantics
    bad = [o.Name for o in doc.Objects if o.State and "Invalid" in str(o.State)]
    print("RECOMPUTED:", n)
    print("BAD:", bad)
    pad = doc.getObject("Pad")
    pocket = doc.getObject("Pocket")
    print("PAD_VOLUME:", round(pad.Shape.Volume, 2))
    print("VALID:", pocket.Shape.isValid())
    print("VOLUME:", round(pocket.Shape.Volume, 2))
    """
)


def test_exported_example_opens_and_recomputes_in_freecad(tmp_path):
    example = Path("examples/mechanical/box-with-hole.FCStd").resolve()
    script = tmp_path / "check.py"
    script.write_text(_CHECK.format(path=str(example)))
    result = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    )
    out = result.stdout
    assert "BAD: []" in out, f"objects failed to recompute:\n{out}\n{result.stderr}"
    assert "RECOMPUTED: 0" not in out  # Touched flags must trigger work on open
    assert "PAD_VOLUME: 8000.0" in out
    assert "VALID: True" in out
    # 40*20*10 box minus a radius-4 through hole: 8000 - pi*16*10 = 7497.35
    assert "VOLUME: 7497.35" in out


def test_fresh_export_recomputes_without_manual_touch(tmp_path):
    # Live-testing regression claim: newly exported (non-example) files needed
    # obj.touch() before recompute. A plain recompute must do the work.
    from forgelab.exporters.mechanical import FreeCADExporter
    from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
    from forgelab.spec.mechanical import Body, Pad, Sketch, SketchGeometry

    sketch = Sketch(
        name="Profile",
        body="MainBody",
        geometry=[
            SketchGeometry(geo_type="line", points=[0, 0, 30, 0]),
            SketchGeometry(geo_type="line", points=[30, 0, 30, 15]),
            SketchGeometry(geo_type="line", points=[30, 15, 0, 15]),
            SketchGeometry(geo_type="line", points=[0, 15, 0, 0]),
        ],
    )
    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="fresh", generator="test"),
        nodes=[
            Node(id="MainBody", type="body", props=Body(name="MainBody").model_dump()),
            Node(id="Profile", type="sketch", props=sketch.model_dump()),
            Node(
                id="BasePad",
                type="pad",
                props=Pad(
                    name="BasePad", body="MainBody", profile="Profile", length=5.0
                ).model_dump(),
            ),
        ],
    )
    fcstd = tmp_path / "fresh.FCStd"
    fcstd.write_bytes(FreeCADExporter().from_ir(doc))
    script = tmp_path / "check.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import FreeCAD as App
            doc = App.openDocument({str(fcstd)!r})
            n = doc.recompute()  # plain recompute, no touch()
            pad = doc.getObject("BasePad")
            print("RECOMPUTED:", n)
            print("PAD_VOLUME:", round(pad.Shape.Volume, 2))
            """
        )
    )
    result = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    )
    assert "RECOMPUTED: 0" not in result.stdout, result.stdout
    assert "PAD_VOLUME: 2250.0" in result.stdout  # 30 * 15 * 5
