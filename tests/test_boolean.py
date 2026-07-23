"""Part booleans: combining two independently-built solids.

Every other mechanical feature works inside one body's own chain, so two
separately-modelled solids could not be joined at all. A ``boolean`` node
unions, cuts or intersects them.

The FreeCAD grammar behind this was read off files FreeCAD 1.1 wrote itself,
and the probing turned up four things worth pinning:

* ``Part::Boolean`` is **abstract** — ``addObject`` rejects it outright. The
  concrete types are ``Part::Cut`` / ``Part::MultiFuse`` / ``Part::MultiCommon``.
* There is **no ``Part::MultiCut``**, so a cut takes exactly one tool.
* A boolean result is a ``Compound``, never a ``Solid``, even when it holds a
  single solid.
* A degenerate boolean does **not** fail: an empty intersection recomputes to a
  valid, "Up-to-date" compound with zero solids and volume 0. Nothing
  downstream catches it, which is why the cut heuristic in ``check_mechanical``
  exists.
"""

import json
import math
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
from forgelab.spec.mechanical import (
    Body,
    Boolean,
    Pad,
    Part,
    Placement,
    Sketch,
    SketchGeometry,
)
from forgelab.validation import check_mechanical

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples/mechanical/bracket_with_boss.forge.json"

_FREECAD = pytest.mark.skipif(shutil.which("freecadcmd") is None, reason="FreeCAD is not installed")

# The fixture geometry every operation test below shares: a 20 x 20 x 10 base
# block and a 10 x 10 x 20 tool block sitting at (0, 0) and rising from z=0, so
# the two overlap in exactly a 10 x 10 x 10 = 1000 mm3 corner.
_BASE_VOLUME = 20 * 20 * 10
_TOOL_VOLUME = 10 * 10 * 20
_OVERLAP = 10 * 10 * 10


def _rect(width: float, height: float) -> list[SketchGeometry]:
    corners = [
        [0.0, 0.0, width, 0.0],
        [width, 0.0, width, height],
        [width, height, 0.0, height],
        [0.0, height, 0.0, 0.0],
    ]
    return [SketchGeometry(geo_type="line", points=c) for c in corners]


def _two_body_doc(
    operation: str, *, tool_z: float = 0.0, tool_height: float = 20.0
) -> ForgeDocument:
    """Two independently-built solids plus the boolean that combines them."""
    tool_sketch = Sketch(
        name="ToolProfile",
        body="ToolBody",
        placement=Placement(position=[0.0, 0.0, tool_z]),
        geometry=_rect(10.0, 10.0),
    )
    pairs = [
        (Part(name="Assembly"), "part"),
        (Body(name="BaseBody", part="Assembly"), "body"),
        (Sketch(name="BaseProfile", body="BaseBody", geometry=_rect(20.0, 20.0)), "sketch"),
        (Pad(name="BasePad", body="BaseBody", profile="BaseProfile", length=10.0), "pad"),
        (Body(name="ToolBody", part="Assembly"), "body"),
        (tool_sketch, "sketch"),
        (Pad(name="ToolPad", body="ToolBody", profile="ToolProfile", length=tool_height), "pad"),
        (
            Boolean(name="Result", operation=operation, base="BaseBody", tools=["ToolBody"]),
            "boolean",
        ),
    ]
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name=f"bool-{operation}", generator="test"),
        nodes=[Node(id=m.name, type=t, props=m.model_dump()) for m, t in pairs],
    )


def _document_xml(doc: ForgeDocument) -> str:
    data = FreeCADExporter().from_ir(doc)
    return zipfile.ZipFile(BytesIO(data)).read("Document.xml").decode()


def _object_block(xml: str, name: str) -> str:
    """One object's ObjectData block — its <Property> list, not its declaration."""
    return xml.split(f'<Object name="{name}"><Properties')[1].split("</Object>")[0]


def _run_freecad(tmp_path: Path, doc: ForgeDocument, script_body: str) -> str:
    fcstd = tmp_path / "b.FCStd"
    fcstd.write_bytes(FreeCADExporter().from_ir(doc))
    script = tmp_path / "check.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import FreeCAD as App
            doc = App.openDocument({str(fcstd)!r})
            n = doc.recompute()  # plain recompute, no touch()
            print("RECOMPUTED:", n)
            print("BAD:", [o.Name for o in doc.Objects
                           if o.State and "Invalid" in str(o.State)])
            """
        )
        + textwrap.dedent(script_body)
    )
    result = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=180
    )
    out = result.stdout
    assert "RECOMPUTED: 0" not in out, out
    assert "BAD: []" in out, f"{out}\n{result.stderr}"
    return out


# ------------------------------------------------------------------- the model


def test_operation_must_be_one_of_the_three():
    assert Boolean(name="B", operation="union", base="A", tools=["C"]).operation == "union"
    with pytest.raises(ValidationError):
        Boolean(name="B", operation="subtract", base="A", tools=["C"])


def test_boolean_needs_a_base_and_at_least_one_tool():
    with pytest.raises(ValidationError):
        Boolean(name="B", operation="union", tools=["C"])  # no base
    with pytest.raises(ValidationError):
        Boolean(name="B", operation="union", base="A")  # no tools


def test_union_and_common_take_several_tools_but_cut_takes_exactly_one():
    """FreeCAD ships Part::MultiFuse and Part::MultiCommon but no
    Part::MultiCut, so a multi-tool cut has no honest representation."""
    assert len(Boolean(name="B", operation="union", base="A", tools=["C", "D"]).tools) == 2
    assert len(Boolean(name="B", operation="common", base="A", tools=["C", "D"]).tools) == 2
    with pytest.raises(ValidationError, match="MultiCut"):
        Boolean(name="B", operation="cut", base="A", tools=["C", "D"])


def test_base_may_not_also_be_a_tool():
    with pytest.raises(ValidationError):
        Boolean(name="B", operation="union", base="A", tools=["A"])


# ---------------------------------------------------------------- the export


@pytest.mark.parametrize(
    ("operation", "fctype"),
    [("union", "Part::MultiFuse"), ("common", "Part::MultiCommon"), ("cut", "Part::Cut")],
)
def test_each_operation_exports_its_concrete_freecad_type(operation, fctype):
    xml = _document_xml(_two_body_doc(operation))
    assert f'<Object type="{fctype}" name="Result"' in xml
    # Part::Boolean is abstract: FreeCAD refuses to instantiate it.
    assert '"Part::Boolean"' not in xml


def test_multi_operations_link_shapes_and_a_cut_links_base_and_tool():
    union = _document_xml(_two_body_doc("union"))
    assert '<Property name="Shapes" type="App::PropertyLinkList">' in union
    assert '<Link value="BaseBody"/><Link value="ToolBody"/>' in union

    cut = _document_xml(_two_body_doc("cut"))
    assert '<Property name="Base" type="App::PropertyLink"><Link value="BaseBody"/>' in cut
    assert '<Property name="Tool" type="App::PropertyLink"><Link value="ToolBody"/>' in cut
    assert '"App::PropertyLinkList"' not in _object_block(cut, "Result")


def test_a_feature_operand_is_lifted_to_the_body_that_owns_it():
    """Linking a pad that lives inside a Body is out of FreeCAD's link scope
    ("go out of the allowed scope", logged live on every recompute), so an
    operand naming a feature is linked as the body instead — which is what
    FreeCAD's own Part > Boolean does with two bodies."""
    doc = _two_body_doc("union")
    for node in doc.nodes:
        if node.type == "boolean":
            node.props["base"], node.props["tools"] = "BasePad", ["ToolPad"]
    xml = _document_xml(doc)
    assert '<Link value="BaseBody"/><Link value="ToolBody"/>' in xml
    assert "BasePad" not in _object_block(xml, "Result")


def test_the_boolean_joins_the_part_group_that_owns_its_operands():
    """Same scope rule one level up: a boolean outside the App::Part holding
    its bodies is flagged, so it is written into that Part's Group."""
    xml = _document_xml(_two_body_doc("union"))
    group = _object_block(xml, "Assembly")
    assert '<Link value="Result"/>' in group


def test_operands_are_hidden_and_the_result_is_shown():
    """A boolean does not delete its inputs — they stay real objects (verified
    live: each input's InList points at the boolean). They are switched off so
    the operands do not draw on top of the result."""
    data = FreeCADExporter().from_ir(_two_body_doc("union"))
    gui = zipfile.ZipFile(BytesIO(data)).read("GuiDocument.xml").decode()

    def visible(name: str) -> bool:
        block = gui.split(f'<ViewProvider name="{name}"')[1].split("</ViewProvider>")[0]
        return '<Bool value="true"/>' in block

    assert visible("Result")
    assert not visible("BaseBody")
    assert not visible("ToolBody")
    assert not visible("BasePad")


def test_boolean_survives_the_sidecar_round_trip():
    from forgelab.importers.mechanical import FreeCADImporter

    doc = _two_body_doc("cut")
    assert FreeCADImporter().to_ir(FreeCADExporter().from_ir(doc)) == doc


# ------------------------------------------------------------- the validation


def test_a_missing_base_or_tool_is_an_error():
    doc = _two_body_doc("union")
    for node in doc.nodes:
        if node.type == "boolean":
            node.props["base"], node.props["tools"] = "NoSuchSolid", ["AlsoMissing"]
    errors, _warnings = check_mechanical(doc)
    assert any("base 'NoSuchSolid'" in e for e in errors), errors
    assert any("tool 'AlsoMissing'" in e for e in errors), errors


def test_resolving_an_operand_by_display_name_is_accepted():
    errors, warnings = check_mechanical(_two_body_doc("union"))
    assert (errors, warnings) == ([], [])


def test_a_cut_whose_tool_cannot_reach_the_base_is_warned_about():
    """The heuristic's whole reason to exist: FreeCAD reports no error at all
    for a cut that removes nothing — it returns a valid compound."""
    doc = _two_body_doc("cut", tool_z=500.0, tool_height=20.0)
    errors, warnings = check_mechanical(doc)
    assert errors == []
    assert any("removes nothing" in w for w in warnings), warnings


def test_the_cut_heuristic_stays_quiet_when_the_boxes_do_overlap():
    _errors, warnings = check_mechanical(_two_body_doc("cut"))
    assert warnings == []


def test_the_cut_heuristic_skips_shapes_whose_extent_it_cannot_derive():
    """It compares parametric bounding boxes, so a loft/revolve/fillet operand
    yields no box and the check passes rather than guessing."""
    doc = _two_body_doc("cut")
    nodes = [n for n in doc.nodes if n.id != "ToolPad"]
    nodes.append(
        Node(
            id="ToolPad",
            type="revolve",
            props={"name": "ToolPad", "body": "ToolBody", "profile": "ToolProfile", "axis": "X"},
        )
    )
    for node in nodes:
        if node.type == "boolean":
            node.props["tools"] = ["ToolPad"]
    _errors, warnings = check_mechanical(doc.model_copy(update={"nodes": nodes}))
    assert not any("removes nothing" in w for w in warnings), warnings


# --------------------------------------------------- live FreeCAD arithmetic


_VOLUME_PROBE = """
    r = doc.getObject("Result")
    base = doc.getObject("BaseBody")
    tool = doc.getObject("ToolBody")
    overlap = base.Shape.common(tool.Shape).Volume
    print("TYPE:", r.TypeId)
    print("BASE:", round(base.Shape.Volume, 3))
    print("TOOL:", round(tool.Shape.Volume, 3))
    print("OVERLAP:", round(overlap, 3))
    print("RESULT:", round(r.Shape.Volume, 3))
    print("SOLIDS:", len(r.Shape.Solids))
    print("SHAPETYPE:", r.Shape.ShapeType)
    """


def _volumes(out: str) -> dict[str, float]:
    return {
        line.split(":")[0]: float(line.split(":")[1])
        for line in out.splitlines()
        if line.split(":")[0] in ("BASE", "TOOL", "OVERLAP", "RESULT")
    }


@_FREECAD
def test_union_of_two_non_overlapping_solids_is_the_sum(tmp_path):
    # The tool starts exactly at the base's top face: they touch, share no
    # volume, and the union is the plain sum.
    doc = _two_body_doc("union", tool_z=10.0, tool_height=20.0)
    out = _run_freecad(tmp_path, doc, _VOLUME_PROBE)
    v = _volumes(out)
    assert v["OVERLAP"] == 0.0
    assert v["RESULT"] == pytest.approx(v["BASE"] + v["TOOL"])
    assert v["RESULT"] == pytest.approx(_BASE_VOLUME + _TOOL_VOLUME)
    assert "SOLIDS: 1" in out  # genuinely joined, not a two-solid compound


@_FREECAD
def test_union_of_two_overlapping_solids_subtracts_the_overlap(tmp_path):
    out = _run_freecad(tmp_path, doc := _two_body_doc("union"), _VOLUME_PROBE)
    assert doc is not None
    v = _volumes(out)
    assert v["OVERLAP"] == pytest.approx(_OVERLAP)
    assert v["RESULT"] < v["BASE"] + v["TOOL"]
    assert v["RESULT"] == pytest.approx(v["BASE"] + v["TOOL"] - v["OVERLAP"])


@_FREECAD
def test_cut_removes_exactly_the_intersection(tmp_path):
    out = _run_freecad(tmp_path, _two_body_doc("cut"), _VOLUME_PROBE)
    v = _volumes(out)
    assert v["RESULT"] == pytest.approx(v["BASE"] - v["OVERLAP"])
    assert v["RESULT"] == pytest.approx(_BASE_VOLUME - _OVERLAP)


@_FREECAD
def test_common_keeps_only_the_overlapping_volume(tmp_path):
    out = _run_freecad(tmp_path, _two_body_doc("common"), _VOLUME_PROBE)
    v = _volumes(out)
    assert v["RESULT"] == pytest.approx(v["OVERLAP"])
    assert v["RESULT"] == pytest.approx(_OVERLAP)


@_FREECAD
def test_a_boolean_result_is_a_compound_not_a_solid(tmp_path):
    """Pinned because it is counter-intuitive and would break any downstream
    check written as ``ShapeType == "Solid"``."""
    out = _run_freecad(tmp_path, _two_body_doc("union"), _VOLUME_PROBE)
    assert "SHAPETYPE: Compound" in out
    assert "SOLIDS: 1" in out


@_FREECAD
def test_no_operand_link_falls_outside_freecads_allowed_scope(tmp_path):
    """FreeCAD logs "Link(s) to object(s) ... go out of the allowed scope" when
    a boolean reaches into a container it does not share. It still computes, so
    only the log catches it."""
    fcstd = tmp_path / "scope.FCStd"
    fcstd.write_bytes(FreeCADExporter().from_ir(_two_body_doc("union")))
    script = tmp_path / "check.py"
    script.write_text(f"import FreeCAD as App\nApp.openDocument({str(fcstd)!r}).recompute()\n")
    result = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=180
    )
    assert "allowed scope" not in result.stdout + result.stderr


# ------------------------------------------------------------ worked example


def test_bracket_with_boss_example_validates():
    doc = validate(json.loads(_EXAMPLE.read_text()))
    assert check_mechanical(doc) == ([], [])
    kinds = [n.type for n in doc.nodes]
    assert kinds.count("body") == 2  # two independently-built solids
    (boolean,) = [n for n in doc.nodes if n.type == "boolean"]
    assert boolean.props["operation"] == "union"
    assert boolean.props["base"] == "Plate" and boolean.props["tools"] == ["Boss"]


@_FREECAD
def test_bracket_with_boss_example_builds_the_computed_volume(tmp_path):
    """The plate and the boss are modelled in separate bodies and the boss is
    sunk 3mm into the plate, so the union has a real overlap to subtract.

    The expected volume is computed from FreeCAD's own operand shapes
    (``plate.Shape.common(boss.Shape)``), not hard-coded — and cross-checked
    against the closed form, so a wrong answer cannot agree with both.
    """
    doc = validate(json.loads(_EXAMPLE.read_text()))
    out = _run_freecad(
        tmp_path,
        doc,
        """
        r = doc.getObject("Bracket_Assembly")
        plate = doc.getObject("Plate")
        boss = doc.getObject("Boss")
        overlap = plate.Shape.common(boss.Shape).Volume
        bb = r.Shape.BoundBox
        print("BASE:", round(plate.Shape.Volume, 3))
        print("TOOL:", round(boss.Shape.Volume, 3))
        print("OVERLAP:", round(overlap, 3))
        print("RESULT:", round(r.Shape.Volume, 3))
        print("SOLIDS:", len(r.Shape.Solids))
        print("VALID:", r.Shape.isValid())
        print("BBOX:", round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3))
        """,
    )
    v = _volumes(out)
    assert "VALID: True" in out
    assert "SOLIDS: 1" in out  # the two bodies really merged into one solid
    # Computed check: union == base + tool - their actual intersection.
    assert v["RESULT"] == pytest.approx(v["BASE"] + v["TOOL"] - v["OVERLAP"])
    # Independent closed form: a 60x40x8 plate plus an r9 x 23 boss sunk 3mm in.
    plate, radius, embed, boss_height = 60 * 40 * 8, 9.0, 3.0, 23.0
    assert v["BASE"] == pytest.approx(plate)
    assert v["TOOL"] == pytest.approx(math.pi * radius**2 * boss_height, rel=1e-4)
    assert v["OVERLAP"] == pytest.approx(math.pi * radius**2 * embed, rel=1e-4)
    assert v["RESULT"] == pytest.approx(
        plate + math.pi * radius**2 * (boss_height - embed), rel=1e-4
    )
    assert v["RESULT"] == pytest.approx(24289.38, abs=0.01)
    # 60 x 40 footprint; the boss tops out 20mm above the 8mm plate.
    assert "BBOX: 60.0 40.0 28.0" in out
