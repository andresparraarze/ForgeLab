"""Part-workbench revolve: Part::Revolution export, validation, live FreeCAD.

The rounded_knob example's expected volume is analytic (Pappus / solid of
revolution over the profile's outer boundary): 986.67*pi = 3099.7mm^3, which
the live FreeCAD recompute reproduces exactly.
"""

import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from forgelab.exporters.mechanical.freecad import FreeCADExporter
from forgelab.spec import SPEC_VERSION, ForgeDocument
from forgelab.validation import check_mechanical

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples/mechanical/rounded_knob.forge.json"


def _profile_node(node_id="profile", plane="XZ_Plane", points=None):
    lines = points or [
        [0.0, 0.0, 6.0, 0.0],
        [6.0, 0.0, 4.0, 10.0],
        [4.0, 10.0, 0.0, 10.0],
        [0.0, 10.0, 0.0, 0.0],
    ]
    return {
        "id": node_id,
        "type": "sketch",
        "props": {
            "name": node_id,
            "body": "b1",
            "plane": plane,
            "geometry": [{"geo_type": "line", "points": p} for p in lines],
        },
    }


def _revolve_node(profile="profile", axis="Z", angle=360.0):
    return {
        "id": "rev1",
        "type": "revolve",
        "props": {
            "name": "Rev",
            "body": "b1",
            "profile": profile,
            "axis": axis,
            "angle": angle,
        },
    }


def _doc(*extra_nodes):
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "mechanical",
            "meta": {"name": "rev-test", "generator": "test"},
            "nodes": [
                {"id": "b1", "type": "body", "props": {"name": "Body"}},
                *extra_nodes,
            ],
        }
    )


def _document_xml(document) -> str:
    data = FreeCADExporter().from_ir(document)
    return zipfile.ZipFile(BytesIO(data)).read("Document.xml").decode()


def _revolve_props(xml_text: str) -> ET.Element:
    root = ET.fromstring(xml_text)
    data = root.find("ObjectData")
    obj = next(o for o in data.findall("Object") if o.get("name") == "rev1")
    return obj.find("Properties")


def _prop(props: ET.Element, name: str) -> ET.Element:
    return next(p for p in props.findall("Property") if p.get("name") == name)


# --------------------------------------------------------------------- export


def test_revolve_exports_part_revolution_with_source_axis_angle():
    xml_text = _document_xml(_doc(_profile_node(), _revolve_node()))
    root = ET.fromstring(xml_text)
    decls = {o.get("name"): o.get("type") for o in root.find("Objects").findall("Object")}
    assert decls["rev1"] == "Part::Revolution"

    props = _revolve_props(xml_text)
    assert _prop(props, "Source").find("Link").get("value") == "profile"
    axis = _prop(props, "Axis").find("PropertyVector")
    assert (axis.get("valueX"), axis.get("valueY"), axis.get("valueZ")) == (
        "0.0000000000000000",
        "0.0000000000000000",
        "1.0000000000000000",
    )
    assert float(_prop(props, "Angle").find("Float").get("value")) == 360.0
    assert _prop(props, "Solid").find("Bool").get("value") == "true"
    base = _prop(props, "Base").find("PropertyVector")
    assert float(base.get("valueX")) == 0.0 and float(base.get("valueZ")) == 0.0


def test_partial_revolve_angle_is_written():
    xml_text = _document_xml(_doc(_profile_node(), _revolve_node(angle=180.0)))
    assert float(_prop(_revolve_props(xml_text), "Angle").find("Float").get("value")) == 180.0


@pytest.mark.parametrize(
    ("axis", "plane", "expected"),
    [
        ("X", "XY_Plane", ("1.0", "0.0", "0.0")),
        ("Y", "XY_Plane", ("0.0", "1.0", "0.0")),
        ("Z", "XZ_Plane", ("0.0", "0.0", "1.0")),
    ],
)
def test_each_axis_option_emits_matching_vector(axis, plane, expected):
    xml_text = _document_xml(_doc(_profile_node(plane=plane), _revolve_node(axis=axis)))
    vec = _prop(_revolve_props(xml_text), "Axis").find("PropertyVector")
    got = (vec.get("valueX"), vec.get("valueY"), vec.get("valueZ"))
    assert tuple(float(v) for v in got) == tuple(float(v) for v in expected)


def test_lowercase_axis_is_normalized_and_bad_axis_rejected():
    from forgelab.spec.mechanical import Revolve

    assert Revolve(name="r", axis="z").axis == "Z"
    with pytest.raises(ValueError, match="axis must be"):
        Revolve(name="r", axis="W")


# ----------------------------------------------------------------- validation


def test_validation_catches_unresolvable_profile():
    errors, _ = check_mechanical(_doc(_profile_node(), _revolve_node(profile="ghost")))
    assert any("revolve 'rev1' references profile 'ghost'" in e for e in errors)


@pytest.mark.parametrize("angle", [0.0, -90.0, 400.0])
def test_validation_catches_bad_angle(angle):
    errors, _ = check_mechanical(_doc(_profile_node(), _revolve_node(angle=angle)))
    assert any("must be > 0 and <= 360" in e for e in errors)


def test_validation_catches_profile_crossing_the_axis():
    # Geometry spans x in [-3, 6]: strictly on both sides of the Z axis.
    crossing = [
        [-3.0, 0.0, 6.0, 0.0],
        [6.0, 0.0, 6.0, 8.0],
        [6.0, 8.0, -3.0, 8.0],
        [-3.0, 8.0, -3.0, 0.0],
    ]
    errors, _ = check_mechanical(_doc(_profile_node(points=crossing), _revolve_node()))
    assert any("crosses the revolution axis" in e for e in errors)


def test_profile_touching_the_axis_is_allowed():
    # The default profile closes along x=0 — touching, not crossing.
    errors, warnings = check_mechanical(_doc(_profile_node(), _revolve_node()))
    assert errors == []
    assert warnings == []


def test_validation_catches_axis_perpendicular_to_sketch_plane():
    # An XY-plane profile revolved around Z: the axis is the sketch normal.
    errors, _ = check_mechanical(_doc(_profile_node(plane="XY_Plane"), _revolve_node(axis="Z")))
    assert any("perpendicular" in e for e in errors)


# -------------------------------------------------------------------- example


def test_rounded_knob_example_validates_and_exports():
    document = ForgeDocument.model_validate(json.loads(_EXAMPLE.read_text()))
    errors, warnings = check_mechanical(document)
    assert errors == []
    assert warnings == []

    data = FreeCADExporter().from_ir(document)
    archive = zipfile.ZipFile(BytesIO(data))
    assert {"Document.xml", "GuiDocument.xml", "ForgeLab.Document.xml"} <= set(archive.namelist())
    root = ET.fromstring(archive.read("Document.xml"))
    types = {o.get("type") for o in root.find("Objects").findall("Object")}
    assert "Part::Revolution" in types
    # The revolve is the terminal (visible) shape.
    gui = archive.read("GuiDocument.xml").decode()
    assert re.search(r'<ViewProvider name="knob_revolve".*?<Bool value="true"/>', gui, re.S)


@pytest.mark.skipif(shutil.which("freecadcmd") is None, reason="FreeCAD is not installed")
def test_rounded_knob_export_recomputes_in_freecad(tmp_path):
    document = ForgeDocument.model_validate(json.loads(_EXAMPLE.read_text()))
    fcstd = tmp_path / "rounded_knob.FCStd"
    fcstd.write_bytes(FreeCADExporter().from_ir(document))
    script = tmp_path / "check.py"
    script.write_text(
        f"import FreeCAD as App\n"
        f"doc = App.openDocument({str(fcstd)!r})\n"
        f"doc.recompute()\n"
        f'bad = [o.Name for o in doc.Objects if o.State and "Invalid" in str(o.State)]\n'
        f'print("BAD:", bad)\n'
        f'rev = doc.getObject("knob_revolve")\n'
        f'print("VALID:", (not rev.Shape.isNull()) and rev.Shape.isValid())\n'
        f'print("VOL_OK:", abs(rev.Shape.Volume - 3099.7) < 5.0)\n'
        f"bb = rev.Shape.BoundBox\n"
        f'print("BBOX_OK:", abs(bb.XMin + 10) < 0.01 and abs(bb.XMax - 10) < 0.01 '
        f"and abs(bb.ZMin) < 0.01 and abs(bb.ZMax - 16) < 0.01)\n"
    )
    result = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    )
    assert "BAD: []" in result.stdout, f"recompute failed:\n{result.stdout}\n{result.stderr}"
    assert "VALID: True" in result.stdout
    assert "VOL_OK: True" in result.stdout
    assert "BBOX_OK: True" in result.stdout
