"""Arc sketch geometry: the third ``geo_type``, and the profiles it unlocks.

Sketches could only draw ``line`` and ``circle``, so a rounded rectangle, a
slot or any filleted 2D outline had no direct expression — the phone-stand
build worked around it with a circle pocket. An ``arc`` is an *open* curve
segment whose two endpoints join adjacent lines, exactly like a line's.

Every angle claim here is pinned to real FreeCAD 1.1 behaviour, probed by
building ``Part.ArcOfCircle`` objects and reading back the saved
``Document.xml``: angles are radians counter-clockwise from +X, the start is
wrapped into ``[0, 2*pi)`` and the end is pushed past it so the sweep is
always positive.
"""

import json
import math
import re
import shutil
import subprocess
import textwrap
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from forgelab.core import validate
from forgelab.exporters.mechanical import FreeCADExporter
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.spec.mechanical import Body, Pad, Part, Sketch, SketchGeometry
from forgelab.validation import check_mechanical

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples/mechanical/rounded_rect_plate.forge.json"

# The rounded-rectangle the example draws: 60 x 40 outline, 8mm corners, 6 thick.
_W, _H, _R, _T = 60.0, 40.0, 8.0, 6.0


def _rounded_rect(width: float, height: float, radius: float) -> list[SketchGeometry]:
    """A counter-clockwise rounded rectangle: 4 straight edges + 4 corner arcs."""

    def line(x1: float, y1: float, x2: float, y2: float) -> SketchGeometry:
        return SketchGeometry(geo_type="line", points=[x1, y1, x2, y2])

    def arc(cx: float, cy: float, start: float, end: float) -> SketchGeometry:
        return SketchGeometry(
            geo_type="arc", center=[cx, cy], radius=radius, start_angle=start, end_angle=end
        )

    w, h, r = width, height, radius
    return [
        line(r, 0.0, w - r, 0.0),
        arc(w - r, r, 270.0, 360.0),
        line(w, r, w, h - r),
        arc(w - r, h - r, 0.0, 90.0),
        line(w - r, h, r, h),
        arc(r, h - r, 90.0, 180.0),
        line(0.0, h - r, 0.0, r),
        arc(r, r, 180.0, 270.0),
    ]


def _plate_doc(geometry: list[SketchGeometry]) -> ForgeDocument:
    pairs = [
        (Part(name="Part"), "part"),
        (Body(name="Body", part="Part"), "body"),
        (Sketch(name="Outline", body="Body", geometry=geometry), "sketch"),
        (Pad(name="Plate", body="Body", profile="Outline", length=_T), "pad"),
    ]
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="plate", generator="test"),
        nodes=[Node(id=m.name, type=t, props=m.model_dump()) for m, t in pairs],
    )


# ---------------------------------------------------------------- the model


def test_arc_needs_a_centre_and_a_non_zero_sweep():
    assert SketchGeometry(geo_type="arc", center=[0, 0], radius=5, end_angle=90.0).radius == 5
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="arc", radius=5, end_angle=90.0)  # no centre
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="arc", center=[0, 0], radius=5)  # start == end
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="arc", center=[0, 0], radius=5, end_angle=90.0, points=[0, 0, 1, 1])


def test_lines_and_circles_may_not_carry_arc_angles():
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="line", points=[0, 0, 1, 0], end_angle=90.0)
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="circle", center=[0, 0], radius=2, start_angle=45.0)


def test_arc_endpoints_follow_the_freecad_angle_convention():
    """Probed live: an arc at (0, 90) around the origin with radius 5 starts at
    (5, 0) and ends at (0, 5) — degrees counter-clockwise from +X."""
    start, end = SketchGeometry(
        geo_type="arc", center=[0.0, 0.0], radius=5.0, start_angle=0.0, end_angle=90.0
    ).endpoints()
    assert start == pytest.approx((5.0, 0.0))
    assert end == pytest.approx((0.0, 5.0), abs=1e-12)


def test_a_circle_has_no_endpoints_to_join():
    with pytest.raises(ValueError, match="closed curve"):
        SketchGeometry(geo_type="circle", center=[0, 0], radius=2).endpoints()


# --------------------------------------------------------------- the export


def _sketch_xml(geometry: list[SketchGeometry]) -> str:
    data = FreeCADExporter().from_ir(_plate_doc(geometry))
    return zipfile.ZipFile(BytesIO(data)).read("Document.xml").decode()


def _arc_elements(xml: str) -> list[dict[str, float]]:
    return [
        {k: float(v) for k, v in re.findall(r'(\w+)="(-?[\d.eE+]+)"', el)}
        for el in re.findall(r"<ArcOfCircle [^>]*/>", xml)
    ]


def test_arc_exports_freecad_arc_of_circle_geometry():
    """The grammar was read off a file FreeCAD wrote itself: a
    ``Part::GeomArcOfCircle`` holding an ``<ArcOfCircle>`` with the circle's
    centre/normal/radius plus StartAngle/EndAngle in radians."""
    xml = _sketch_xml(
        [
            SketchGeometry(
                geo_type="arc", center=[10.0, 0.0], radius=5.0, start_angle=0.0, end_angle=90.0
            )
        ]
    )
    assert 'type="Part::GeomArcOfCircle"' in xml
    (arc,) = _arc_elements(xml)
    assert (arc["CenterX"], arc["CenterY"], arc["CenterZ"]) == (10.0, 0.0, 0.0)
    assert (arc["NormalX"], arc["NormalY"], arc["NormalZ"]) == (0.0, 0.0, 1.0)
    assert arc["Radius"] == 5.0
    assert arc["StartAngle"] == pytest.approx(0.0)
    assert arc["EndAngle"] == pytest.approx(math.pi / 2)


@pytest.mark.parametrize(
    ("start_deg", "end_deg", "expected"),
    [
        # Every row measured from FreeCAD 1.1's own saved Document.xml.
        (0.0, 90.0, (0.0, 1.570796)),
        (90.0, 180.0, (1.570796, 3.141592)),
        (270.0, 360.0, (4.712388, 6.283185)),
        (-90.0, 0.0, (4.712388, 6.283185)),  # normalized to the same arc
        (170.0, 190.0, (2.967059, 3.316125)),
        (350.0, 10.0, (6.108652, 6.457718)),  # sweep wraps past +X
    ],
)
def test_arc_angles_normalize_the_way_freecad_normalizes_them(start_deg, end_deg, expected):
    (arc,) = _arc_elements(
        _sketch_xml(
            [
                SketchGeometry(
                    geo_type="arc",
                    center=[0.0, 0.0],
                    radius=5.0,
                    start_angle=start_deg,
                    end_angle=end_deg,
                )
            ]
        )
    )
    assert (arc["StartAngle"], arc["EndAngle"]) == pytest.approx(expected, abs=1e-5)
    assert arc["EndAngle"] > arc["StartAngle"]  # the sweep is always positive


def test_arc_survives_the_sidecar_round_trip():
    from forgelab.importers.mechanical import FreeCADImporter

    doc = _plate_doc(_rounded_rect(_W, _H, _R))
    assert FreeCADImporter().to_ir(FreeCADExporter().from_ir(doc)) == doc


# ------------------------------------------------------------ profile closure


def test_closed_profile_mixing_lines_and_arcs_passes_the_closure_check():
    errors, warnings = check_mechanical(_plate_doc(_rounded_rect(_W, _H, _R)))
    assert errors == []
    assert warnings == []


def test_open_line_and_arc_profile_is_rejected():
    """Drop one straight edge: the two arc endpoints it joined are now loose."""
    geometry = [g for g in _rounded_rect(_W, _H, _R) if g.geo_type == "arc"] + [
        SketchGeometry(geo_type="line", points=[_R, 0.0, _W - _R, 0.0])
    ]
    _errors, warnings = check_mechanical(_plate_doc(geometry))
    assert any("not a closed loop" in w for w in warnings), warnings


def test_arc_that_does_not_reach_its_neighbours_is_rejected():
    """A corner arc with the wrong radius still *looks* like a rounded rect but
    leaves a gap at both ends — the endpoints are what the check compares."""
    geometry = _rounded_rect(_W, _H, _R)
    geometry[1] = SketchGeometry(
        geo_type="arc", center=[_W - _R, _R], radius=_R + 1.0, start_angle=270.0, end_angle=360.0
    )
    _errors, warnings = check_mechanical(_plate_doc(geometry))
    assert any("not a closed loop" in w for w in warnings), warnings


def test_arc_with_a_non_positive_radius_is_an_error():
    doc = _plate_doc([SketchGeometry(geo_type="arc", center=[0, 0], radius=0.0, end_angle=90.0)])
    errors, _warnings = check_mechanical(doc)
    assert any("arc with radius <= 0" in e for e in errors), errors


# ------------------------------------------------------------- worked example


def test_rounded_rect_plate_example_validates():
    doc = validate(json.loads(_EXAMPLE.read_text()))
    errors, warnings = check_mechanical(doc)
    assert (errors, warnings) == ([], [])
    (sketch,) = [n for n in doc.nodes if n.type == "sketch"]
    kinds = [g["geo_type"] for g in sketch.props["geometry"]]
    assert kinds.count("line") == 4 and kinds.count("arc") == 4


@pytest.mark.skipif(shutil.which("freecadcmd") is None, reason="FreeCAD is not installed")
def test_rounded_rect_plate_example_builds_the_right_solid_in_freecad(tmp_path):
    """The live check: FreeCAD recomputes the example and the solid it builds
    has the volume and bounding box a rounded rectangle must have.

    A wrong angle convention (radians vs degrees, clockwise, or measured from
    +Y) still produces a closed-looking sketch, so volume alone is not enough —
    the bounding box pins the arcs to the corners they belong in.
    """
    doc = validate(json.loads(_EXAMPLE.read_text()))
    fcstd = tmp_path / "plate.FCStd"
    fcstd.write_bytes(FreeCADExporter().from_ir(doc))
    script = tmp_path / "check.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import FreeCAD as App
            doc = App.openDocument({str(fcstd)!r})
            n = doc.recompute()  # plain recompute, no touch()
            print("RECOMPUTED:", n)
            print("BAD:", [o.Name for o in doc.Objects if o.State and "Invalid" in str(o.State)])
            sk = doc.getObject("Outline")
            print("GEO:", [g.TypeId.split("Geom")[-1] for g in sk.Geometry])
            print("EDGES:", len(sk.Shape.Edges))
            pad = doc.getObject("Plate")
            bb = pad.Shape.BoundBox
            print("VALID:", pad.Shape.isValid())
            print("VOLUME:", round(pad.Shape.Volume, 3))
            print("BBOX:", round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3))
            print("ORIGIN:", round(bb.XMin, 3), round(bb.YMin, 3), round(bb.ZMin, 3))
            """
        )
    )
    out = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    ).stdout
    assert "RECOMPUTED: 0" not in out, out
    assert "BAD: []" in out, out
    # FreeCAD read back four real arcs, alternating with the straight edges.
    assert "GEO: " + str(["LineSegment", "ArcOfCircle"] * 4) in out, out
    assert "EDGES: 8" in out, out  # 4 lines + 4 arcs, no stray geometry
    assert "VALID: True" in out, out
    # 60*40*6 minus the four corners the arcs round off: (4 - pi) * 8**2 * 6.
    volume = round(_W * _H * _T - (4 - math.pi) * _R**2 * _T, 3)
    assert f"VOLUME: {volume}" in out, out
    assert volume == pytest.approx(14070.372, abs=0.001)
    assert "BBOX: 60.0 40.0 6.0" in out, out
    assert "ORIGIN: 0.0 0.0 0.0" in out, out
