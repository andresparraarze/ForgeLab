"""Previewing a mechanical part: the kernel tessellates, the renderer draws.

A threed document contains its triangles. A mechanical one contains a recipe,
so these tests are about getting real geometry out of FreeCAD and into the
renderer without mangling it on the way — above all without applying the
threed domain's Y-up axis remap to coordinates that are already Z-up.
"""

import json
from pathlib import Path

import pytest
from external_tools import requires_freecad

from forgelab.core import validate
from forgelab.preview import PreviewError, render_preview
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples/mechanical"


def _example(name: str) -> ForgeDocument:
    return validate(json.loads((_EXAMPLES / name).read_text()))


def _tower(height: float = 40.0) -> ForgeDocument:
    """A 10x10 footprint padded ``height`` tall — deliberately not cubic."""
    nodes = [
        Node(id="B", type="body", props={"name": "B"}),
        Node(
            id="S",
            type="sketch",
            props={
                "name": "S",
                "body": "B",
                "plane": "XY",
                "geometry": [
                    {"geo_type": "line", "points": [0, 0, 10, 0]},
                    {"geo_type": "line", "points": [10, 0, 10, 10]},
                    {"geo_type": "line", "points": [10, 10, 0, 10]},
                    {"geo_type": "line", "points": [0, 10, 0, 0]},
                ],
            },
        ),
        Node(
            id="P", type="pad", props={"name": "P", "body": "B", "profile": "S", "length": height}
        ),
    ]
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="tower"),
        nodes=nodes,
    )


@requires_freecad
def test_mechanical_geometry_stays_z_up():
    """The single most consequential detail: no Y-up remap on FreeCAD output.

    A pad extrudes along the sketch plane's normal, so a 10x10 profile on XY
    padded 40mm is 40 tall in Z. The threed renderer maps (x, y, z) -> (x, -z, y)
    because glTF is Y-up; applying that here would report the part as 10 tall
    and 40 deep — every mechanical part laid on its side, in every preview.
    """
    from forgelab.preview.mechanical import collect_triangles

    triangles, _ = collect_triangles(_tower(height=40.0))
    assert triangles

    points = [p for tri in triangles for p in tri]
    extent = [max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)]
    assert extent == pytest.approx([10.0, 10.0, 40.0], abs=1e-6)


@requires_freecad
def test_only_finished_solids_are_tessellated():
    """A body and its tip are one shape; drawing both paints them over each other."""
    from forgelab.preview.mechanical import collect_triangles

    # A box tessellates to 12 triangles. The body and its tip pad are the same
    # shape, so taking both would give 24 — the exact double-count that made a
    # 10mm cube measure 1975 mm^3 instead of 975.
    triangles, _ = collect_triangles(_tower())
    assert len(triangles) == 12


@requires_freecad
def test_each_solid_gets_its_own_colour():
    """A multi-solid part must not read as one undifferentiated blob."""
    from forgelab.preview.mechanical import _SOLID_COLORS, collect_triangles

    triangles, colors = collect_triangles(_tower())
    assert len(colors) == len(triangles)
    assert set(colors) == {_SOLID_COLORS[0]}


@requires_freecad
@pytest.mark.parametrize(
    "name", ["motor_mount.forge.json", "enclosure.forge.json", "rounded_knob.forge.json"]
)
def test_examples_render_to_a_real_png(tmp_path, name):
    out = tmp_path / "preview.png"
    result = render_preview(_example(name), str(out), views=4)

    assert result["triangle_count"] > 100
    assert result["views"] == ["iso", "front", "right", "top"]
    assert out.stat().st_size > 5000
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@requires_freecad
def test_mechanical_views_are_engineering_views_not_scene_views(tmp_path):
    """A part is read as a drawing: a pictorial view plus orthographic elevations."""
    result = render_preview(_example("motor_mount.forge.json"), str(tmp_path / "p.png"), views=3)
    assert result["views"] == ["iso", "front", "right"]
    # The threed presets would be wrong here.
    assert "front-3/4" not in result["views"]


@requires_freecad
def test_a_part_that_builds_nothing_reports_why(tmp_path):
    """An empty body has no solids; say so, and point at the diagnosis."""
    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="empty"),
        nodes=[Node(id="B", type="body", props={"name": "B"})],
    )
    with pytest.raises(PreviewError, match="no solid geometry"):
        render_preview(doc, str(tmp_path / "p.png"))


def test_hardware_documents_are_still_refused(tmp_path):
    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.HARDWARE,
        meta=DocumentMeta(name="board"),
        nodes=[],
    )
    with pytest.raises(PreviewError, match="threed and mechanical"):
        render_preview(doc, str(tmp_path / "p.png"))
