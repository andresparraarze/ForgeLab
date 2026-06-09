import pytest
from pydantic import ValidationError

from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SKETCH,
    Body,
    Constraint,
    Pad,
    Part,
    Placement,
    Pocket,
    Sketch,
    SketchGeometry,
)


def test_node_type_constants():
    assert (NODE_PART, NODE_BODY, NODE_SKETCH, NODE_PAD, NODE_POCKET) == (
        "part",
        "body",
        "sketch",
        "pad",
        "pocket",
    )


def test_placement_defaults_to_identity():
    p = Placement()
    assert p.position == [0.0, 0.0, 0.0]
    assert p.rotation == [0.0, 0.0, 0.0, 1.0]


def test_placement_validates_lengths():
    with pytest.raises(ValidationError):
        Placement(position=[0.0, 0.0])
    with pytest.raises(ValidationError):
        Placement(rotation=[0.0, 0.0, 0.0])


def test_line_geometry_requires_four_points():
    line = SketchGeometry(geo_type="line", points=[0.0, 0.0, 40.0, 0.0])
    assert line.points == [0.0, 0.0, 40.0, 0.0]
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="line", points=[0.0, 0.0])


def test_circle_geometry_requires_center():
    circle = SketchGeometry(geo_type="circle", center=[20.0, 10.0], radius=4.0)
    assert circle.radius == 4.0
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="circle", center=[20.0])


def test_unknown_geo_type_rejected():
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="spline", points=[0.0, 0.0, 1.0, 1.0])


def test_models_forbid_extra_fields():
    with pytest.raises(ValidationError):
        Pad(name="Pad", length=10.0, bogus=1)


def test_sketch_holds_geometry_and_constraints():
    sketch = Sketch(
        name="Sketch",
        body="Body",
        geometry=[SketchGeometry(geo_type="circle", center=[0.0, 0.0], radius=2.0)],
        constraints=[Constraint(ctype="Radius", value=2.0, name="r")],
    )
    assert sketch.plane == "XY_Plane"
    assert sketch.constraints[0].value == 2.0


def test_pad_and_pocket_links_and_flags():
    pad = Pad(name="Pad", body="Body", profile="Sketch", length=10.0)
    assert pad.reversed is False and pad.midplane is False
    pocket = Pocket(name="Pocket", body="Body", profile="Sketch001", through_all=True)
    assert pocket.through_all is True
    part = Part(name="Part")
    body = Body(name="Body", part="Part")
    assert body.part == "Part" and part.name == "Part"
