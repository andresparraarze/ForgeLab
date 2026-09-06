"""Geometric verification against the real FreeCAD kernel.

Two halves. The solid-selection tests are pure Python and run everywhere — they
pin which objects a geometry consumer should read, which is where the
double-counting bugs live. The rest need FreeCAD and skip without it, exactly
like ``test_freecad_e2e.py``.

What makes these tests worth having: every "broken" document below passes
``check_mechanical`` with no errors and no warnings. That is the point. The
cheap checks cannot see that a shell collapsed or a fillet was impossible,
because only OpenCASCADE knows — and FreeCAD reports no error either, leaving a
valid, "Up-to-date" object holding nothing at all.
"""

import json
import shutil
from pathlib import Path

import pytest

from forgelab.core import validate
from forgelab.exporters.mechanical import FreeCADExporter
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.validation.mechanical import check_mechanical
from forgelab.verify import VerifyError, verify_document

needs_freecad = pytest.mark.skipif(
    shutil.which("freecadcmd") is None, reason="FreeCAD is not installed"
)

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples/mechanical"
_EXAMPLE_NAMES = sorted(p.name for p in _EXAMPLES.glob("*.forge.json"))


def _example(name: str) -> ForgeDocument:
    return validate(json.loads((_EXAMPLES / name).read_text()))


def _cube_doc(*extra: Node) -> ForgeDocument:
    """A 10mm cube body (sketch + pad), plus whatever features are appended."""
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
        Node(id="P", type="pad", props={"name": "P", "body": "B", "profile": "S", "length": 10.0}),
        *extra,
    ]
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="cube"),
        nodes=nodes,
    )


# --- solid selection (no FreeCAD needed) ------------------------------------ #


@pytest.mark.parametrize("name", _EXAMPLE_NAMES)
def test_each_example_reports_exactly_one_finished_solid(name):
    """Every shipped example is one part, so it must select one solid.

    Selecting more means double counting: handing Part.export a body AND its tip
    writes the same shape twice (a 20790-byte STEP for a part that is 8439).
    """
    build = FreeCADExporter().build(_example(name))
    assert len(build.solid_names) == 1, f"{name} selected {build.solid_names}"


def test_a_fillet_supersedes_the_body_whose_tip_it_rounds():
    """The body renders its tip's shape, so counting both doubles the part."""
    doc = _cube_doc(
        Node(id="F", type="fillet", props={"name": "F", "body": "B", "target": "P", "radius": 1.0})
    )
    assert FreeCADExporter().build(doc).solid_names == ("F",)


def test_a_body_holding_only_part_features_is_not_expected_to_have_a_shape():
    """A loft/revolve never becomes a tip, so its body's null shape is normal.

    organic_grip and rounded_knob are both built this way; treating their empty
    bodies as failures would fail two perfectly good examples.
    """
    build = FreeCADExporter().build(_example("organic_grip.forge.json"))
    assert build.solid_names == ("grip_fillet",)
    assert build.solid_body_names == ()


def test_a_body_with_a_pad_chain_is_expected_to_have_a_shape():
    build = FreeCADExporter().build(_example("motor_mount.forge.json"))
    assert build.solid_body_names == ("Body",)


def test_only_the_finished_shape_is_left_visible(tmp_path):
    """Regression: FreeCAD drew the raw pad on top of the fillet built from it.

    Both were marked visible, so the part looked entirely unfilleted on open and
    the fillet appeared to be a no-op.
    """
    import io
    import re
    import zipfile

    doc = _cube_doc(
        Node(id="F", type="fillet", props={"name": "F", "body": "B", "target": "P", "radius": 1.0})
    )
    archive = zipfile.ZipFile(io.BytesIO(FreeCADExporter().from_ir(doc)))
    gui = archive.read("GuiDocument.xml").decode()
    visibility = dict(re.findall(r'<ViewProvider name="(\w+)".*?value="(\w+)"', gui, re.S))
    assert visibility["F"] == "true"
    for superseded in ("B", "P", "S"):
        assert visibility[superseded] == "false", f"{superseded} would be drawn over the fillet"


def test_verification_rejects_a_non_mechanical_document():
    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.THREED,
        meta=DocumentMeta(name="scene"),
        nodes=[],
    )
    with pytest.raises(VerifyError, match="mechanical documents only"):
        verify_document(doc)


# --- real kernel ------------------------------------------------------------ #


@needs_freecad
@pytest.mark.parametrize("name", _EXAMPLE_NAMES)
def test_every_shipped_example_actually_builds(name):
    """The regression net: each example must recompute to a real solid."""
    report = verify_document(_example(name))
    assert report["verified"], f"{name}: {report['errors']}"
    assert report["solid_count"] >= 1
    assert report["total_volume"] > 0.0
    assert report["bbox"] is not None


@needs_freecad
def test_motor_mount_volume_matches_its_described_dimensions():
    """A plate minus its bore and holes — arithmetic the kernel has to agree with.

    100x60x3 = 18000 mm^3, less a 19mm-radius through bore (pi*19^2*3 = 3402).
    The eight mounting holes take a further ~290, so the solid lands just under
    14300 rather than at some arbitrary number.
    """
    report = verify_document(_example("motor_mount.forge.json"))
    assert 14200 < report["total_volume"] < 14400
    assert report["bbox"][:2] == pytest.approx([0.0, 0.0], abs=1e-6)
    assert report["bbox"][3:5] == pytest.approx([100.0, 60.0], abs=1e-6)


@needs_freecad
def test_an_impossible_fillet_radius_is_caught_although_every_cheap_check_passes():
    """A 50mm round on a 10mm cube. Nothing but the kernel can know."""
    doc = _cube_doc(
        Node(id="F", type="fillet", props={"name": "F", "body": "B", "target": "P", "radius": 50.0})
    )
    assert check_mechanical(doc) == ([], []), "the premise: cheap checks see nothing wrong"

    report = verify_document(doc)
    assert not report["verified"]
    assert report["total_volume"] == 0.0
    assert any("'F'" in e for e in report["errors"])


@needs_freecad
def test_a_shell_with_no_opening_is_caught_although_every_cheap_check_passes():
    """The trap the Shell docstring warns about in prose, now actually detected.

    ``Shell`` says a solid with no ``faces_to_remove`` "exports but produces a
    null shape on recompute". Until now nothing enforced that.
    """
    doc = _cube_doc(
        Node(
            id="H", type="shell", props={"name": "H", "body": "B", "target": "P", "thickness": 1.0}
        )
    )
    assert check_mechanical(doc) == ([], []), "the premise: cheap checks see nothing wrong"

    report = verify_document(doc)
    assert not report["verified"]
    assert any("'H'" in e for e in report["errors"])


@needs_freecad
def test_a_sound_fillet_verifies_and_removes_the_volume_it_should():
    """The same shape with a workable radius: 12 edges rounded off a 1000mm^3 cube."""
    doc = _cube_doc(
        Node(id="F", type="fillet", props={"name": "F", "body": "B", "target": "P", "radius": 1.0})
    )
    report = verify_document(doc)
    assert report["verified"], report["errors"]
    assert report["solid_count"] == 1
    # Not 2000: the body and the fillet are one part, not two.
    assert 970 < report["total_volume"] < 1000


@needs_freecad
def test_each_node_is_reported_under_its_own_ir_id():
    """Diagnostics name IR nodes, not FreeCAD's internal object names."""
    report = verify_document(_example("motor_mount.forge.json"))
    by_id = {n["node_id"]: n for n in report["nodes"]}
    assert {"MotorMount", "Body", "Plate", "PlatePad"} <= set(by_id)
    assert by_id["PlatePad"]["type"] == "pad"
    assert by_id["Body"]["final"] is True
    assert by_id["Plate"]["final"] is False  # a sketch is not a finished solid


# --- MCP surface ------------------------------------------------------------ #


def _write(tmp_path: Path, doc: ForgeDocument) -> str:
    path = tmp_path / "part.forge.json"
    path.write_text(json.dumps(doc.model_dump(mode="json")))
    return str(path)


def test_generation_status_reports_whether_the_kernel_is_reachable():
    """An agent should know before it calls, not after it fails."""
    from forgelab.mcp import tools

    status = tools.generation_status()
    assert isinstance(status["freecad_kernel"], bool)
    assert status["verify_geometry"] == status["freecad_kernel"]
    if not status["freecad_kernel"]:
        # The .FCStd exporter is pure stdlib; the reason must not suggest
        # mechanical export is broken without FreeCAD.
        assert "still export to .FCStd" in status["freecad_reason"]


def test_mcp_verify_geometry_rejects_a_non_mechanical_document(tmp_path):
    from forgelab.mcp import tools

    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.THREED,
        meta=DocumentMeta(name="scene"),
        nodes=[],
    )
    with pytest.raises(ValueError, match="mechanical documents only"):
        tools.verify_geometry(_write(tmp_path, doc))


def test_mcp_verify_geometry_rejects_an_unparseable_document(tmp_path):
    from forgelab.mcp import tools

    path = tmp_path / "broken.forge.json"
    path.write_text('{"domain": "mechanical"}')
    with pytest.raises(ValueError, match="invalid document"):
        tools.verify_geometry(str(path))


@needs_freecad
def test_mcp_verify_geometry_reports_a_good_part(tmp_path):
    from forgelab.mcp import tools

    report = tools.verify_geometry(_write(tmp_path, _example("motor_mount.forge.json")))
    assert report["verified"]
    assert report["solid_count"] == 1


@needs_freecad
def test_mcp_verify_geometry_reports_a_broken_part(tmp_path):
    from forgelab.mcp import tools

    doc = _cube_doc(
        Node(id="F", type="fillet", props={"name": "F", "body": "B", "target": "P", "radius": 50.0})
    )
    report = tools.verify_geometry(_write(tmp_path, doc))
    assert not report["verified"]
    assert report["errors"]


@needs_freecad
def test_a_feature_built_on_the_wrong_predecessor_is_warned_about():
    """Found by accident while exercising the tool, which is why it is pinned.

    The fillet targets the pad instead of the last pocket, so FreeCAD builds two
    independent solids overlapping in space: the fully-pocketed body, and a
    fillet of the raw pad that still has no holes in it. Every individual
    feature is valid, so this is a warning rather than an error — a document may
    legitimately hold several parts — but for a part meant to be one solid it is
    the signature of a mis-chained feature.
    """
    doc = _cube_doc(
        Node(
            id="Hole",
            type="sketch",
            props={
                "name": "Hole",
                "body": "B",
                "plane": "XY",
                "geometry": [{"geo_type": "circle", "center": [5.0, 5.0], "radius": 2.0}],
            },
        ),
        Node(
            id="HoleCut",
            type="pocket",
            props={
                "name": "HoleCut",
                "body": "B",
                "profile": "Hole",
                "through_all": True,
                "reversed": True,
            },
        ),
        # Wrong: targets the pad, not HoleCut, the last feature in the chain.
        Node(id="F", type="fillet", props={"name": "F", "body": "B", "target": "P", "radius": 1.0}),
    )
    report = verify_document(doc)
    assert report["verified"], report["errors"]  # nothing actually failed to build
    assert report["solid_count"] == 2
    assert any("wrong predecessor" in w for w in report["warnings"])


@needs_freecad
def test_reported_bbox_is_the_true_extent_not_the_conservative_bound():
    """OCC's cheap BoundBox over-reports on curved shapes; the exact one is used.

    A filleted 10mm cube measured -0.494 to 10.494 through ``Shape.BoundBox`` —
    half a millimetre of fiction on every side, on a number a caller would
    reasonably read as the part's dimensions.
    """
    doc = _cube_doc(
        Node(id="F", type="fillet", props={"name": "F", "body": "B", "target": "P", "radius": 1.0})
    )
    report = verify_document(doc)
    assert report["bbox"] == pytest.approx([0.0, 0.0, 0.0, 10.0, 10.0, 10.0], abs=1e-6)
