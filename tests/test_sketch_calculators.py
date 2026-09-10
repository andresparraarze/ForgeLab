"""Sketch-profile calculators, checked against the validator that judges them.

The load-bearing property is closure. An open profile cannot be padded, and the
failure is silent-ish: the document validates with a warning and the part comes
out empty. So rather than asserting coordinates the calculators themselves
produced, these tests feed each profile to the real closed-loop check in
``forgelab.validation.mechanical`` — the same one a generated document is held
to — and to the real ``SketchGeometry`` model.
"""

import math

import pytest
from external_tools import requires_freecad

from forgelab.calc import calculate_bolt_circle, calculate_rounded_rect, calculate_slot
from forgelab.spec import SPEC_VERSION
from forgelab.spec.mechanical import Sketch, SketchGeometry
from forgelab.validation.mechanical import _segments_form_closed_loop


def _closed(geometry: list[dict]) -> bool:
    """True when the open curves in ``geometry`` pair up into closed loops."""
    segments = []
    for geo in geometry:
        model = SketchGeometry.model_validate(geo)
        if model.geo_type != "circle":
            segments.append(model.endpoints())
    return _segments_form_closed_loop(segments)


def _validates(geometry: list[dict]) -> Sketch:
    """Every primitive must satisfy the real domain model, not just look right."""
    return Sketch.model_validate({"name": "S", "geometry": geometry})


# --- bolt circle ------------------------------------------------------------ #


def test_bolt_circle_places_holes_on_the_circle_at_even_spacing():
    holes = calculate_bolt_circle(4, radius=15.5, hole_radius=1.7, center=[50.0, 30.0])
    _validates(holes)
    assert len(holes) == 4
    for hole in holes:
        cx, cy = hole["center"]
        assert math.hypot(cx - 50.0, cy - 30.0) == pytest.approx(15.5)
        assert hole["radius"] == 1.7
    # First hole on +X from the centre, then counter-clockwise.
    assert holes[0]["center"] == pytest.approx([65.5, 30.0])
    assert holes[1]["center"] == pytest.approx([50.0, 45.5])


def test_bolt_circle_honours_a_start_angle():
    """A 4-hole pattern at 45 degrees is the NEMA-style diagonal arrangement."""
    holes = calculate_bolt_circle(4, radius=10.0, hole_radius=1.0, start_angle=45.0)
    for hole in holes:
        cx, cy = hole["center"]
        assert abs(cx) == pytest.approx(abs(cy))  # all on the diagonals


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(count=0, radius=10.0, hole_radius=1.0), "at least 1 hole"),
        (dict(count=4, radius=0.0, hole_radius=1.0), "radius must be > 0"),
        (dict(count=4, radius=10.0, hole_radius=0.0), "not a diameter"),
        (dict(count=4, radius=10.0, hole_radius=10.0), "swallow the pattern centre"),
    ],
)
def test_bolt_circle_rejects_impossible_patterns(kwargs, message):
    with pytest.raises(ValueError, match=message):
        calculate_bolt_circle(**kwargs)


# --- rounded rectangle ------------------------------------------------------ #


def test_rounded_rect_is_a_closed_profile():
    """The whole reason this exists: eight coupled pieces of trigonometry."""
    profile = calculate_rounded_rect(60.0, 40.0, 5.0)
    _validates(profile)
    assert _closed(profile), "the arcs do not meet the lines"


@pytest.mark.parametrize("origin", [None, [12.5, -7.25]])
@pytest.mark.parametrize("radius", [0.5, 3.0, 9.99])
def test_rounded_rect_closes_at_any_size_and_position(origin, radius):
    profile = calculate_rounded_rect(30.0, 20.0, radius, origin)
    assert _closed(profile)


def test_rounded_rect_spans_exactly_the_requested_extent():
    """Rounding the corners must not shrink the part."""
    profile = calculate_rounded_rect(60.0, 40.0, 5.0, [10.0, 20.0])
    xs, ys = [], []
    for geo in profile:
        if geo["geo_type"] == "line":
            p = geo["points"]
            xs += [p[0], p[2]]
            ys += [p[1], p[3]]
        else:
            cx, cy = geo["center"]
            r = geo["radius"]
            xs += [cx - r, cx + r]
            ys += [cy - r, cy + r]
    assert (min(xs), max(xs)) == pytest.approx((10.0, 70.0))
    assert (min(ys), max(ys)) == pytest.approx((20.0, 60.0))


def test_rounded_rect_has_four_lines_and_four_quarter_arcs():
    profile = calculate_rounded_rect(60.0, 40.0, 5.0)
    kinds = [geo["geo_type"] for geo in profile]
    assert kinds.count("line") == 4
    assert kinds.count("arc") == 4
    for geo in profile:
        if geo["geo_type"] == "arc":
            sweep = (geo["end_angle"] - geo["start_angle"]) % 360.0
            assert sweep == pytest.approx(90.0)


@pytest.mark.parametrize(
    "args, message",
    [
        ((60.0, 40.0, 0.0), "must be > 0"),
        ((60.0, 40.0, 20.0), "too large"),
        ((10.0, 40.0, 5.0), "too large"),
    ],
)
def test_rounded_rect_rejects_impossible_corners(args, message):
    with pytest.raises(ValueError, match=message):
        calculate_rounded_rect(*args)


# --- slot ------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "ends",
    [
        (0.0, 0.0, 20.0, 0.0),  # horizontal
        (0.0, 0.0, 0.0, 20.0),  # vertical
        (5.0, 5.0, 25.0, 17.0),  # diagonal
        (25.0, 17.0, 5.0, 5.0),  # the same diagonal, reversed
    ],
)
def test_slot_is_closed_at_any_orientation(ends):
    profile = calculate_slot(*ends, width=6.0)
    _validates(profile)
    assert _closed(profile), f"slot {ends} does not close"


def test_slot_length_is_cap_distance_plus_width():
    """The documented convention: the given points are cap CENTRES."""
    profile = calculate_slot(0.0, 0.0, 20.0, 0.0, width=6.0)
    xs = []
    for geo in profile:
        if geo["geo_type"] == "line":
            xs += [geo["points"][0], geo["points"][2]]
        else:
            xs += [geo["center"][0] - geo["radius"], geo["center"][0] + geo["radius"]]
    assert max(xs) - min(xs) == pytest.approx(26.0)


def test_slot_rejects_a_zero_length_run():
    with pytest.raises(ValueError, match="use a circle primitive instead"):
        calculate_slot(4.0, 4.0, 4.0, 4.0, width=6.0)


def test_slot_rejects_a_zero_width():
    with pytest.raises(ValueError, match="width must be > 0"):
        calculate_slot(0.0, 0.0, 10.0, 0.0, width=0.0)


# --- MCP surface ------------------------------------------------------------ #


def test_calculators_are_exposed_as_mcp_tools():
    from forgelab.mcp import tools

    assert _closed(tools.calculate_rounded_rect(40.0, 25.0, 4.0))
    assert _closed(tools.calculate_slot(0.0, 0.0, 15.0, 0.0, 5.0))
    assert len(tools.calculate_bolt_circle(6, 20.0, 1.7)) == 6


# --- end to end ------------------------------------------------------------- #


@requires_freecad
def test_calculated_profiles_build_a_real_solid_in_freecad():
    """The claim that matters: these profiles pad and pocket in the real kernel.

    The closed-loop check above is the project's own heuristic. This is the
    kernel's verdict on the same geometry: a rounded plate with a bolt circle
    pocketed through it.
    """
    from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
    from forgelab.verify import verify_document

    doc = ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="calcplate"),
        nodes=[
            Node(id="B", type="body", props={"name": "B"}),
            Node(
                id="Plate",
                type="sketch",
                props={
                    "name": "Plate",
                    "body": "B",
                    "plane": "XY",
                    "geometry": calculate_rounded_rect(80, 50, 8),
                },
            ),
            Node(
                id="Pad",
                type="pad",
                props={"name": "Pad", "body": "B", "profile": "Plate", "length": 4.0},
            ),
            Node(
                id="Bolts",
                type="sketch",
                props={
                    "name": "Bolts",
                    "body": "B",
                    "plane": "XY",
                    "geometry": calculate_bolt_circle(6, 20.0, 2.2, center=[40, 25]),
                },
            ),
            Node(
                id="BoltCut",
                type="pocket",
                props={
                    "name": "BoltCut",
                    "body": "B",
                    "profile": "Bolts",
                    "through_all": True,
                    "reversed": True,
                },
            ),
        ],
    )
    report = verify_document(doc)
    assert report["verified"], report["errors"]
    assert report["solid_count"] == 1
    # A 80x50x4 blank is 16000 mm^3; rounding four r=8 corners and drilling six
    # r=2.2 holes takes off a few hundred, so the solid lands just under 15500.
    assert 15000 < report["total_volume"] < 15600
    # The exact bounding box is computed from triangulation, so it carries ~1e-7
    # of noise. Still nine orders of magnitude below anything dimensional.
    assert report["bbox"][:3] == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert report["bbox"][3:] == pytest.approx([80.0, 50.0, 4.0], abs=1e-6)
