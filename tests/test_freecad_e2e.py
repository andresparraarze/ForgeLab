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


def test_motor_mount_example_with_short_plane_names_recomputes(tmp_path):
    # Bug fix: the motor-mount example spells its planes "XY"/"XZ" (not the exact
    # "XY_Plane"/"XZ_Plane"). The exporter must still attach every sketch to a
    # datum plane, so the vertical flange orients and all solids build on a plain
    # recompute — the live-testing failure was AttachmentSupport silently dropped
    # for any non-canonical plane spelling.
    example = Path("examples/mechanical/motor-mount.FCStd").resolve()
    script = tmp_path / "check.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import FreeCAD as App
            doc = App.openDocument({str(example)!r})
            n = doc.recompute()  # plain recompute, no touch()
            flange = doc.getObject("Flange")
            roll = round(flange.Placement.Rotation.toEuler()[2], 1)
            print("RECOMPUTED:", n)
            print("FLANGE_ROLL:", roll)
            for name in ("BasePad", "ShaftHole", "FlangePad"):
                o = doc.getObject(name)
                print(name + "_VOLUME:", round(o.Shape.Volume, 2), o.Shape.isValid())
            """
        )
    )
    out = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    ).stdout
    assert "RECOMPUTED: 0" not in out, out
    assert "FLANGE_ROLL: 90.0" in out, out  # flange genuinely vertical, not flat XY
    assert "BasePad_VOLUME: 28800.0 True" in out, out
    assert "ShaftHole_VOLUME: 26085.66 True" in out, out
    assert "FlangePad_VOLUME: 40485.66 True" in out, out


def test_non_xy_sketch_pocket_cuts_in_freecad(tmp_path):
    # Bug fix: a pocket whose sketch is on a vertical (XZ) plane must orient and
    # cut on plain recompute — previously the sketch landed flat in XY and the
    # pocket removed nothing (which also made the Profile look unlinked).
    from forgelab.exporters.mechanical import FreeCADExporter
    from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
    from forgelab.spec.mechanical import Body, Pad, Pocket, Sketch, SketchGeometry

    base = Sketch(
        name="Base",
        body="Body",
        geometry=[
            SketchGeometry(geo_type="line", points=[0, 0, 40, 0]),
            SketchGeometry(geo_type="line", points=[40, 0, 40, 20]),
            SketchGeometry(geo_type="line", points=[40, 20, 0, 20]),
            SketchGeometry(geo_type="line", points=[0, 20, 0, 0]),
        ],
    )
    hole = Sketch(
        name="Hole",
        body="Body",
        plane="XZ_Plane",
        geometry=[SketchGeometry(geo_type="circle", center=[20, 15], radius=5.0)],
    )
    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="vpart", generator="test"),
        nodes=[
            Node(id="Body", type="body", props=Body(name="Body").model_dump()),
            Node(id="Base", type="sketch", props=base.model_dump()),
            Node(
                id="Pad",
                type="pad",
                props=Pad(name="Pad", body="Body", profile="Base", length=30.0).model_dump(),
            ),
            Node(id="Hole", type="sketch", props=hole.model_dump()),
            Node(
                id="Pocket",
                type="pocket",
                props=Pocket(
                    name="Pocket", body="Body", profile="Hole", through_all=True
                ).model_dump(),
            ),
        ],
    )
    fcstd = tmp_path / "vpart.FCStd"
    fcstd.write_bytes(FreeCADExporter().from_ir(doc))
    script = tmp_path / "check.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import FreeCAD as App
            doc = App.openDocument({str(fcstd)!r})
            n = doc.recompute()
            pad = doc.getObject("Pad")
            pk = doc.getObject("Pocket")
            print("RECOMPUTED:", n)
            print("PROFILE_OK:", pk.Profile[0].Name == "Hole")
            print("PAD_VOLUME:", round(pad.Shape.Volume, 2))
            print("POCKET_VOLUME:", round(pk.Shape.Volume, 2))
            """
        )
    )
    out = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    ).stdout
    assert "RECOMPUTED: 0" not in out, out
    assert "PROFILE_OK: True" in out, out  # Bug 1: Profile resolves on open
    assert "PAD_VOLUME: 24000.0" in out, out
    # Bug 2: the vertical pocket actually removed material (40*20*30 - pi*25*20).
    assert "POCKET_VOLUME: 22429.2" in out, out


def test_through_all_pocket_cuts_without_reversed(tmp_path):
    # Live bug: a through-all pocket (Type=1) whose `reversed` is not set cut
    # nothing — it cut away from the material, leaving the plate volume at 18000.
    # Midplane=true (cut both directions) makes a through-hole cut regardless.
    from forgelab.exporters.mechanical import FreeCADExporter
    from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
    from forgelab.spec.mechanical import Body, Pad, Pocket, Sketch, SketchGeometry

    plate = Sketch(
        name="PlateSk",
        body="Body",
        geometry=[
            SketchGeometry(geo_type="line", points=[0, 0, 60, 0]),
            SketchGeometry(geo_type="line", points=[60, 0, 60, 30]),
            SketchGeometry(geo_type="line", points=[60, 30, 0, 30]),
            SketchGeometry(geo_type="line", points=[0, 30, 0, 0]),
        ],
    )
    bore = Sketch(
        name="BoreSk",
        body="Body",
        geometry=[SketchGeometry(geo_type="circle", center=[30, 15], radius=8.0)],
    )
    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="plate", generator="test"),
        nodes=[
            Node(id="Body", type="body", props=Body(name="Body").model_dump()),
            Node(id="PlateSk", type="sketch", props=plate.model_dump()),
            Node(
                id="Plate",
                type="pad",
                props=Pad(name="Plate", body="Body", profile="PlateSk", length=10.0).model_dump(),
            ),
            Node(id="BoreSk", type="sketch", props=bore.model_dump()),
            # through_all, reversed left at its default (False) — the failing case
            Node(
                id="cut_pocket",
                type="pocket",
                props=Pocket(
                    name="cut_pocket", body="Body", profile="BoreSk", through_all=True
                ).model_dump(),
            ),
        ],
    )
    fcstd = tmp_path / "plate.FCStd"
    fcstd.write_bytes(FreeCADExporter().from_ir(doc))
    script = tmp_path / "check.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import FreeCAD as App
            doc = App.openDocument({str(fcstd)!r})
            doc.recompute()
            pk = doc.getObject("cut_pocket")
            print("POCKET_VOLUME:", round(pk.Shape.Volume, 1))
            print("CUTS:", pk.Shape.Volume < 18000)
            """
        )
    )
    out = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    ).stdout
    assert "CUTS: True" in out, out  # 18000 plate minus the bore
    assert "POCKET_VOLUME: 15989.4" in out, out  # 18000 - pi*64*10
