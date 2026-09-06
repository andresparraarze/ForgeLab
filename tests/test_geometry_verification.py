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
import math
from pathlib import Path

import pytest
from external_tools import requires_freecad

from forgelab.core import validate
from forgelab.exporters.mechanical import FreeCADExporter, realxml
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.validation.mechanical import check_mechanical
from forgelab.verify import VerifyError, verify_document

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


@requires_freecad
@pytest.mark.parametrize("name", _EXAMPLE_NAMES)
def test_every_shipped_example_actually_builds(name):
    """The regression net: each example must recompute to a real solid."""
    report = verify_document(_example(name))
    assert report["verified"], f"{name}: {report['errors']}"
    assert report["solid_count"] >= 1
    assert report["total_volume"] > 0.0
    assert report["bbox"] is not None


@requires_freecad
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


@requires_freecad
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


@requires_freecad
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


@requires_freecad
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


@requires_freecad
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


@requires_freecad
def test_mcp_verify_geometry_reports_a_good_part(tmp_path):
    from forgelab.mcp import tools

    report = tools.verify_geometry(_write(tmp_path, _example("motor_mount.forge.json")))
    assert report["verified"]
    assert report["solid_count"] == 1


@requires_freecad
def test_mcp_verify_geometry_reports_a_broken_part(tmp_path):
    from forgelab.mcp import tools

    doc = _cube_doc(
        Node(id="F", type="fillet", props={"name": "F", "body": "B", "target": "P", "radius": 50.0})
    )
    report = tools.verify_geometry(_write(tmp_path, doc))
    assert not report["verified"]
    assert report["errors"]


@requires_freecad
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


@requires_freecad
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


# --- features that built something, but not what was asked for -------------- #
#
# The checks above ask "did this build?". These ask the harder question: "did it
# do what it said?" A feature can produce a perfectly valid solid that is simply
# not the one the document describes, and every check the project had before
# this — cheap and geometric alike — calls that a success.


def test_the_exporter_records_what_it_guessed_for_an_all_edges_fillet():
    """No FreeCAD needed: the estimate has to be visible before it can be checked.

    A fillet with an explicit ``edges`` list is a fact and is not recorded; only
    the derived counts are, because only those can be wrong.
    """
    derived = FreeCADExporter().build(
        _cube_doc(Node(id="F", type="fillet", props={"name": "F", "target": "P", "radius": 1.0}))
    )
    assert derived.estimated_fillet_edges == {"F": 12}

    explicit = FreeCADExporter().build(
        _cube_doc(
            Node(
                id="F",
                type="fillet",
                props={"name": "F", "target": "P", "radius": 1.0, "edges": [1, 2]},
            )
        )
    )
    assert explicit.estimated_fillet_edges == {}


@requires_freecad
def test_the_estimate_matches_the_kernel_for_every_shipped_example():
    """The regression net for _estimate_edge_count, against ground truth.

    Its formulas were pinned experimentally against FreeCAD 1.1 and have never
    had anything to hold them to account. This is that.
    """
    for name in _EXAMPLE_NAMES:
        doc = _example(name)
        if not FreeCADExporter().build(doc).estimated_fillet_edges:
            continue
        report = verify_document(doc)
        assert not [e for e in report["errors"] if "asks to round every edge" in e], name


@requires_freecad
def test_an_undercounted_all_edges_fillet_is_reported(monkeypatch):
    """The silent failure this check exists for, forced into the open.

    An under-count is invisible to everything else: the part builds, the volume
    is plausible, and some edges are just left sharp — the one outcome someone
    asking to round every edge would notice at a glance and no check would.
    The estimator is right today, so the wrong answer is injected rather than
    waiting for a shape it gets wrong; what is under test is the detection.
    """
    monkeypatch.setattr(realxml, "_estimate_edge_count", lambda *a, **k: 4)
    doc = _cube_doc(Node(id="F", type="fillet", props={"name": "F", "target": "P", "radius": 0.5}))
    assert check_mechanical(doc) == ([], [])  # the cheap checks see nothing wrong

    report = verify_document(doc)
    assert not report["verified"]
    message = next(e for e in report["errors"] if e.startswith("fillet 'F'"))
    assert "derived 4 edges" in message
    assert "the kernel reports 12" in message
    assert "8 edges were left sharp" in message


@requires_freecad
def test_an_overcounted_fillet_still_fails_the_way_it_always_did():
    """The other direction needs no new check: FreeCAD refuses outright.

    Worth pinning so the two failures stay distinguishable — an impossible
    fillet is a recompute failure, not a miscount.
    """
    doc = _cube_doc(
        Node(
            id="F",
            type="fillet",
            props={"name": "F", "target": "P", "radius": 0.5, "edges": list(range(1, 21))},
        )
    )
    report = verify_document(doc)
    assert not report["verified"]
    assert any("failed to recompute" in e for e in report["errors"])


@requires_freecad
def test_a_shell_that_hollows_nothing_is_reported():
    """verify_geometry called a no-op shell 'verified' before this.

    check_mechanical catches this particular document by a different route
    (thickness <= 0), but verify_geometry is a tool of its own and an agent may
    reach for it alone; reporting a solid that was never hollowed as verified
    is the wrong answer whichever other check exists.
    """
    doc = _cube_doc(
        Node(
            id="H",
            type="shell",
            props={"name": "H", "target": "P", "thickness": 0.0, "faces_to_remove": [1]},
        )
    )
    report = verify_document(doc)
    assert not report["verified"]
    assert any("hollowed nothing" in e for e in report["errors"])


@requires_freecad
def test_a_healthy_shell_and_fillet_are_left_alone():
    """The control: neither check may fire on a part that is fine."""
    for feature in (
        Node(id="F", type="fillet", props={"name": "F", "target": "P", "radius": 1.0}),
        Node(
            id="H",
            type="shell",
            props={"name": "H", "target": "P", "thickness": 2.0, "faces_to_remove": [1]},
        ),
    ):
        report = verify_document(_cube_doc(feature))
        assert report["verified"], report["errors"]
        assert report["total_volume"] < 1000.0  # material really was removed


def _pocketed_cube(**pocket_props):
    """A 20mm cube with a Ø6 pocket sketched on XY — the classic wrong-way cut."""
    props = {"name": "K", "body": "B", "profile": "S2", "length": 5.0}
    props.update(pocket_props)
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="pocketed"),
        nodes=[
            Node(id="B", type="body", props={"name": "B"}),
            Node(
                id="S",
                type="sketch",
                props={
                    "name": "S",
                    "body": "B",
                    "plane": "XY",
                    "geometry": [
                        {"geo_type": "line", "points": [0, 0, 20, 0]},
                        {"geo_type": "line", "points": [20, 0, 20, 20]},
                        {"geo_type": "line", "points": [20, 20, 0, 20]},
                        {"geo_type": "line", "points": [0, 20, 0, 0]},
                    ],
                },
            ),
            Node(
                id="P", type="pad", props={"name": "P", "body": "B", "profile": "S", "length": 10.0}
            ),
            Node(
                id="S2",
                type="sketch",
                props={
                    "name": "S2",
                    "body": "B",
                    "plane": "XY",
                    "geometry": [{"geo_type": "circle", "center": [10, 10], "radius": 3.0}],
                },
            ),
            Node(id="K", type="pocket", props=props),
        ],
    )


@requires_freecad
def test_a_pocket_that_cuts_nothing_is_reported():
    """The most likely mistake in the whole mechanical vocabulary.

    A sketch on the XY plane cuts *downward*, so a pocket over a pad that rises
    from z=0 removes nothing at all unless ``reversed`` is true. Found while
    testing the fillet check, in a document written without thinking about it —
    the part built, exported, rendered, and had no hole, and both check_mechanical
    and verify_geometry called it fine.
    """
    doc = _pocketed_cube()
    assert check_mechanical(doc) == ([], [])  # the cheap checks cannot see this

    report = verify_document(doc)
    assert not report["verified"]
    message = next(e for e in report["errors"] if e.startswith("pocket 'K'"))
    assert "cut nothing" in message
    assert "reversed" in message  # the message has to say what to do about it


@requires_freecad
def test_a_pocket_that_cuts_the_right_way_is_left_alone():
    """The control, pinned to arithmetic: 20x20x10 less a Ø6 pocket 5 deep."""
    report = verify_document(_pocketed_cube(reversed=True))
    assert report["verified"], report["errors"]
    assert report["total_volume"] == pytest.approx(20 * 20 * 10 - math.pi * 9 * 5, abs=1e-6)
