"""Part-workbench features (loft/sweep/fillet/shell): export, validation, example.

The exporter writes the parametric description only; FreeCAD's own OCC kernel
computes the real NURBS geometry on recompute. These tests check the emitted
native XML (Part::Loft / Part::Sweep / Part::Fillet / Part::Thickness), the
binary FilletEdges payload, the constraint sanity checks, and the shipped
organic_grip example.
"""

import json
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from forgelab.exporters.mechanical import FreeCADExporter
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.spec import SPEC_VERSION, ForgeDocument
from forgelab.validation import check_mechanical

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples/mechanical/organic_grip.forge.json"


def _circle_sketch(node_id: str, z: float, radius: float) -> dict:
    return {
        "id": node_id,
        "type": "sketch",
        "props": {
            "name": node_id,
            "body": "Body",
            "plane": "XY_Plane",
            "placement": {"position": [0.0, 0.0, z]},
            "geometry": [{"geo_type": "circle", "center": [0.0, 0.0], "radius": radius}],
        },
    }


def _doc(*extra_nodes: dict) -> ForgeDocument:
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "mechanical",
            "meta": {"name": "part-features", "generator": "test"},
            "nodes": [
                {"id": "Body", "type": "body", "props": {"name": "Body"}},
                _circle_sketch("ProfA", 0.0, 10.0),
                _circle_sketch("ProfB", 30.0, 6.0),
                *extra_nodes,
            ],
        }
    )


def _loft_node(**props) -> dict:
    base = {"name": "Loft", "body": "Body", "profiles": ["ProfA", "ProfB"]}
    base.update(props)
    return {"id": "Loft", "type": "loft", "props": base}


def _export(document: ForgeDocument) -> zipfile.ZipFile:
    return zipfile.ZipFile(BytesIO(FreeCADExporter().from_ir(document)))


def _object_xml(archive: zipfile.ZipFile, name: str) -> str:
    xml = archive.read("Document.xml").decode()
    match = re.search(rf'<Object name="{name}">.*?</Object>', xml, re.S)
    assert match is not None, f"object {name!r} not found in Document.xml"
    return match.group(0)


def _decode_fillet_edges(blob: bytes) -> list[tuple[int, float, float]]:
    (count,) = struct.unpack_from("<I", blob, 0)
    return [struct.unpack_from("<idd", blob, 4 + i * 20) for i in range(count)]


# ---------------------------------------------------------------- loft export


def test_loft_exports_part_loft_with_sections_in_order():
    archive = _export(_doc(_loft_node()))
    xml = archive.read("Document.xml").decode()
    assert '<Object type="Part::Loft" name="Loft"' in xml
    loft = _object_xml(archive, "Loft")
    sections = re.search(r'<Property name="Sections".*?</Property>', loft, re.S)
    assert sections is not None
    links = re.findall(r'<Link value="([^"]+)"/>', sections.group(0))
    assert links == ["ProfA", "ProfB"]
    # A loft must build a solid, not a surface shell.
    assert re.search(r'<Property name="Solid"[^>]*>\s*<Bool value="true"/>', loft)


def test_smooth_vs_ruled_loft():
    smooth = _object_xml(_export(_doc(_loft_node(ruled=False))), "Loft")
    ruled = _object_xml(_export(_doc(_loft_node(ruled=True))), "Loft")
    assert re.search(r'<Property name="Ruled"[^>]*>\s*<Bool value="false"/>', smooth)
    assert re.search(r'<Property name="Ruled"[^>]*>\s*<Bool value="true"/>', ruled)


def test_closed_loft():
    closed = _object_xml(_export(_doc(_loft_node(closed=True))), "Loft")
    assert re.search(r'<Property name="Closed"[^>]*>\s*<Bool value="true"/>', closed)


# --------------------------------------------------------------- sweep export


def _sweep_doc(frenet: bool) -> ForgeDocument:
    path = {
        "id": "Path",
        "type": "sketch",
        "props": {
            "name": "Path",
            "body": "Body",
            "plane": "XZ_Plane",
            "geometry": [{"geo_type": "line", "points": [0.0, 0.0, 0.0, 40.0]}],
        },
    }
    sweep = {
        "id": "Sweep",
        "type": "sweep",
        "props": {
            "name": "Sweep",
            "body": "Body",
            "profile": "ProfA",
            "path": "Path",
            "frenet": frenet,
        },
    }
    return _doc(path, sweep)


@pytest.mark.parametrize("frenet", [False, True])
def test_sweep_exports_sections_spine_and_frenet(frenet):
    archive = _export(_sweep_doc(frenet))
    xml = archive.read("Document.xml").decode()
    assert '<Object type="Part::Sweep" name="Sweep"' in xml
    sweep = _object_xml(archive, "Sweep")
    sections = re.search(r'<Property name="Sections".*?</Property>', sweep, re.S)
    assert sections is not None and '<Link value="ProfA"/>' in sections.group(0)
    assert re.search(r'<Property name="Spine"[^>]*>\s*<LinkSub value="Path"', sweep)
    value = "true" if frenet else "false"
    assert re.search(rf'<Property name="Frenet"[^>]*>\s*<Bool value="{value}"/>', sweep)


def test_sweep_path_sketch_is_not_warned_open():
    # A sweep path is deliberately an open curve; the closed-loop sketch
    # warning must not fire for it.
    errors, warnings = check_mechanical(_sweep_doc(False))
    assert errors == []
    assert warnings == []


# -------------------------------------------------------------- fillet export


def _fillet_node(**props) -> dict:
    base = {"name": "Fillet", "body": "Body", "target": "Loft", "radius": 1.5}
    base.update(props)
    return {"id": "Fillet", "type": "fillet", "props": base}


def test_fillet_with_explicit_edges():
    archive = _export(_doc(_loft_node(), _fillet_node(edges=[1, 3])))
    fillet = _object_xml(archive, "Fillet")
    assert re.search(r'<Property name="Base"[^>]*>\s*<Link value="Loft"/>', fillet)
    assert '<FilletEdges file="Fillet.Edges"/>' in fillet
    edges = _decode_fillet_edges(archive.read("Fillet.Edges"))
    assert edges == [(1, 1.5, 1.5), (3, 1.5, 1.5)]


def test_fillet_with_omitted_edges_resolves_all_edges():
    # A smooth open loft between two 1-segment (circle) profiles has 3 edges:
    # the two section rings plus the side seam (verified in FreeCAD 1.1).
    archive = _export(_doc(_loft_node(), _fillet_node()))
    edges = _decode_fillet_edges(archive.read("Fillet.Edges"))
    assert edges == [(1, 1.5, 1.5), (2, 1.5, 1.5), (3, 1.5, 1.5)]


def test_fillet_all_edges_on_ruled_three_section_loft():
    # A ruled loft of k sections of m segments has (2k-1)*m edges: k rings
    # plus a seam per span (verified in FreeCAD 1.1: 3 circles -> 5 edges).
    doc = _doc(
        _circle_sketch("ProfC", 60.0, 8.0),
        _loft_node(profiles=["ProfA", "ProfB", "ProfC"], ruled=True),
        _fillet_node(),
    )
    edges = _decode_fillet_edges(_export(doc).read("Fillet.Edges"))
    assert [e[0] for e in edges] == [1, 2, 3, 4, 5]


def test_fillet_all_edges_on_unresolvable_target_raises():
    pocket = {
        "id": "Cut",
        "type": "pocket",
        "props": {"name": "Cut", "body": "Body", "profile": "ProfA", "through_all": True},
    }
    doc = _doc(pocket, _fillet_node(target="Cut"))
    with pytest.raises(ValueError, match="edge count"):
        FreeCADExporter().from_ir(doc)


# --------------------------------------------------------------- shell export


def _shell_node(**props) -> dict:
    base = {"name": "Shell", "body": "Body", "target": "Loft", "thickness": 2.0}
    base.update(props)
    return {"id": "Shell", "type": "shell", "props": base}


def test_shell_with_faces_to_remove():
    archive = _export(_doc(_loft_node(), _shell_node(faces_to_remove=[2])))
    xml = archive.read("Document.xml").decode()
    assert '<Object type="Part::Thickness" name="Shell"' in xml
    shell = _object_xml(archive, "Shell")
    faces = re.search(r'<Property name="Faces"[^>]*>\s*<LinkSub value="Loft" count="1">', shell)
    assert faces is not None
    assert '<Sub value="Face2"/>' in shell
    # Negative offset hollows inward, keeping the outer surface (FreeCAD
    # convention, verified: 20mm cube / 2mm wall / open top -> volume 3392).
    assert re.search(r'<Property name="Value"[^>]*>\s*<Float value="-2\.0+"/>', shell)


def test_shell_fully_closed():
    shell = _object_xml(_export(_doc(_loft_node(), _shell_node())), "Shell")
    assert re.search(r'<LinkSub value="Loft" count="0">', shell)


# ------------------------------------------------------------------ round-trip


def test_part_features_roundtrip_through_sidecar():
    doc = _doc(_loft_node(), _fillet_node(), _shell_node(faces_to_remove=[1, 2]))
    data = FreeCADExporter().from_ir(doc)
    imported = FreeCADImporter().to_ir(data)
    props_of = {n.id: n.props for n in imported.nodes}
    assert props_of["Loft"]["profiles"] == ["ProfA", "ProfB"]
    assert props_of["Fillet"]["edges"] is None  # None (all edges) survives
    assert props_of["Fillet"]["radius"] == 1.5
    assert props_of["Shell"]["faces_to_remove"] == [1, 2]


# ------------------------------------------------------------------ validation


def test_validation_catches_loft_with_too_few_profiles():
    errors, _ = check_mechanical(_doc(_loft_node(profiles=["ProfA"])))
    assert any("at least 2" in e for e in errors)


def test_validation_catches_nonpositive_fillet_radius_and_shell_thickness():
    doc = _doc(_loft_node(), _fillet_node(radius=0.0), _shell_node(thickness=-1.0))
    errors, _ = check_mechanical(doc)
    assert any("fillet 'Fillet' has radius <= 0" in e for e in errors)
    assert any("shell 'Shell' has thickness <= 0" in e for e in errors)


def test_validation_catches_unresolvable_references():
    sweep = {
        "id": "Sweep",
        "type": "sweep",
        "props": {"name": "Sweep", "body": "Body", "profile": "ProfA", "path": "NoPath"},
    }
    doc = _doc(
        _loft_node(profiles=["ProfA", "Ghost"]),
        _fillet_node(target="Nothing"),
        sweep,
    )
    errors, _ = check_mechanical(doc)
    assert any("profile 'Ghost'" in e for e in errors)
    assert any("target 'Nothing'" in e for e in errors)
    assert any("path 'NoPath'" in e for e in errors)


def test_validation_passes_valid_part_features():
    errors, warnings = check_mechanical(_doc(_loft_node(), _fillet_node()))
    assert errors == []
    assert warnings == []


# --------------------------------------------------------------------- example


def test_organic_grip_example_validates_and_exports():
    document = ForgeDocument.model_validate(json.loads(_EXAMPLE.read_text()))
    errors, warnings = check_mechanical(document)
    assert errors == []
    assert warnings == []

    data = FreeCADExporter().from_ir(document)
    archive = zipfile.ZipFile(BytesIO(data))
    assert {"Document.xml", "GuiDocument.xml", "ForgeLab.Document.xml"} <= set(archive.namelist())
    root = ET.fromstring(archive.read("Document.xml"))  # well-formed XML
    types = {o.get("type") for o in root.find("Objects").findall("Object")}
    assert "Part::Loft" in types
    assert "Part::Fillet" in types
    # The finished shape (the fillet) is visible; the intermediate loft is not.
    gui = archive.read("GuiDocument.xml").decode()
    assert re.search(r'<ViewProvider name="grip_fillet".*?<Bool value="true"/>', gui, re.S)
    assert re.search(r'<ViewProvider name="grip_loft".*?<Bool value="false"/>', gui, re.S)


@pytest.mark.skipif(shutil.which("freecadcmd") is None, reason="FreeCAD is not installed")
def test_organic_grip_export_recomputes_in_freecad(tmp_path):
    document = ForgeDocument.model_validate(json.loads(_EXAMPLE.read_text()))
    fcstd = tmp_path / "organic_grip.FCStd"
    fcstd.write_bytes(FreeCADExporter().from_ir(document))
    script = tmp_path / "check.py"
    script.write_text(
        f"import FreeCAD as App\n"
        f"doc = App.openDocument({str(fcstd)!r})\n"
        f"doc.recompute()\n"
        f'bad = [o.Name for o in doc.Objects if o.State and "Invalid" in str(o.State)]\n'
        f'print("BAD:", bad)\n'
        f'fillet = doc.getObject("grip_fillet")\n'
        f'print("VALID:", (not fillet.Shape.isNull()) and fillet.Shape.isValid())\n'
        f'print("VOLUME_OK:", fillet.Shape.Volume > 1000)\n'
    )
    result = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    )
    assert "BAD: []" in result.stdout, f"recompute failed:\n{result.stdout}\n{result.stderr}"
    assert "VALID: True" in result.stdout
    assert "VOLUME_OK: True" in result.stdout
