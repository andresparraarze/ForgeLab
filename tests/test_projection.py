import pytest

from forgelab.core import validate
from forgelab.projection import PROJECTION_LEVELS, project, projection_schema
from forgelab.spec import SPEC_VERSION


def _hardware():
    return validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "hardware",
            "meta": {"name": "blinky", "generator": "test", "description": "a board"},
            "nodes": [
                {
                    "id": "board",
                    "type": "board",
                    "props": {
                        "kicad_version": "20240108",
                        "generator": "test",
                        "layers": [],
                        "outline": [],
                        "design_rules": {
                            "clearance": 0.2,
                            "track_width": 0.25,
                            "via_diameter": 0.8,
                            "via_drill": 0.4,
                        },
                    },
                },
                {"id": "net:1", "type": "net", "props": {"code": 1, "name": "GND"}},
                {
                    "id": "R1",
                    "type": "component",
                    "props": {
                        "reference": "R1",
                        "value": "330R",
                        "footprint": "Resistor_SMD:R_0402",
                        "layer": "F.Cu",
                        "at": [1.0, 2.0, 0.0],
                        "pads": [
                            {
                                "number": "1",
                                "net": "GND",
                                "at": [-1.0, 0.0],
                                "size": [1.0, 1.0],
                                "shape": "rect",
                            }
                        ],
                    },
                },
            ],
        }
    )


def _threed():
    return validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "threed",
            "meta": {"name": "Scene", "generator": "test", "description": None},
            "nodes": [
                {"id": "Scene", "type": "scene", "props": {"name": "Scene"}},
                {
                    "id": "mat_red",
                    "type": "material",
                    "props": {
                        "name": "red",
                        "base_color": [1.0, 0.0, 0.0, 1.0],
                        "metallic": 1.0,
                        "roughness": 1.0,
                    },
                },
                {
                    "id": "mesh_cube",
                    "type": "mesh",
                    "props": {
                        "name": "cube",
                        "primitives": [
                            {
                                "positions": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0],
                                "indices": [0, 1, 2],
                                "material": "mat_red",
                            }
                        ],
                    },
                },
                {
                    "id": "Cube",
                    "type": "object",
                    "props": {
                        "name": "Cube",
                        "mesh": "mesh_cube",
                        "transform": {
                            "translation": [0.0, 0.0, 0.0],
                            "rotation": [0.0, 0.0, 0.0, 1.0],
                            "scale": [1.0, 1.0, 1.0],
                        },
                    },
                },
            ],
        }
    )


def _mechanical():
    return validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "mechanical",
            "meta": {"name": "box", "generator": "test", "description": None},
            "nodes": [
                {"id": "Part", "type": "part", "props": {"name": "Part"}},
                {"id": "Body", "type": "body", "props": {"name": "Body", "part": "Part"}},
                {
                    "id": "Sketch",
                    "type": "sketch",
                    "props": {
                        "name": "Sketch",
                        "body": "Body",
                        "plane": "XY_Plane",
                        "geometry": [{"geo_type": "line", "points": [0.0, 0.0, 1.0, 0.0]}],
                        "constraints": [],
                    },
                },
                {
                    "id": "Pad",
                    "type": "pad",
                    "props": {"name": "Pad", "body": "Body", "profile": "Sketch", "length": 5.0},
                },
            ],
        }
    )


# --------------------------------------------------------------------------- #
# metadata
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("doc_fn", [_hardware, _threed, _mechanical])
def test_metadata_has_no_node_data(doc_fn):
    out = project(doc_fn(), "metadata")
    assert set(out) == {"forgelab_version", "domain", "meta", "node_count", "nodes_by_type"}
    assert set(out["meta"]) == {"name", "description", "generator"}
    assert "nodes" not in out
    assert out["node_count"] == sum(out["nodes_by_type"].values())


def test_metadata_counts_by_type():
    out = project(_hardware(), "metadata")
    assert out["nodes_by_type"] == {"board": 1, "net": 1, "component": 1}


# --------------------------------------------------------------------------- #
# topology
# --------------------------------------------------------------------------- #
def test_topology_hardware_strips_pad_coordinates():
    out = project(_hardware(), "topology")
    comp = next(n for n in out["nodes"] if n["type"] == "component")
    assert comp["props"]["reference"] == "R1"
    assert comp["props"]["value"] == "330R"
    assert comp["props"]["footprint"] == "Resistor_SMD:R_0402"
    pad = comp["props"]["pads"][0]
    assert pad == {"number": "1", "net": "GND"}
    assert "at" not in pad and "size" not in pad and "shape" not in pad
    # The board node carries no design-rule props at topology.
    board = next(n for n in out["nodes"] if n["type"] == "board")
    assert "props" not in board


def test_topology_threed_strips_mesh_geometry():
    out = project(_threed(), "topology")
    obj = next(n for n in out["nodes"] if n["type"] == "object")
    assert set(obj["props"]) == {"name", "mesh", "transform"}
    mesh = next(n for n in out["nodes"] if n["type"] == "mesh")
    assert "primitives" not in mesh["props"]
    assert mesh["props"] == {"name": "cube"}


def test_topology_mechanical_is_prop_keys_only():
    out = project(_mechanical(), "topology")
    sketch = next(n for n in out["nodes"] if n["type"] == "sketch")
    assert "props" not in sketch
    assert "geometry" in sketch["prop_keys"]  # the key is named, but no geometry data
    assert sketch["prop_keys"] == sorted(["name", "body", "plane", "geometry", "constraints"])


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def test_geometry_hardware_keeps_pads_strips_board():
    out = project(_hardware(), "geometry")
    types = {n["type"] for n in out["nodes"]}
    assert "board" not in types  # board constraints stripped
    comp = next(n for n in out["nodes"] if n["type"] == "component")
    assert comp["props"]["pads"][0]["at"] == [-1.0, 0.0]  # full pad geometry retained


def test_geometry_threed_keeps_mesh_strips_material_and_scene():
    out = project(_threed(), "geometry")
    types = {n["type"] for n in out["nodes"]}
    assert "material" not in types and "scene" not in types
    mesh = next(n for n in out["nodes"] if n["type"] == "mesh")
    assert mesh["props"]["primitives"][0]["positions"]  # full geometry retained


def test_geometry_mechanical_keeps_sketch_geometry():
    out = project(_mechanical(), "geometry")
    sketch = next(n for n in out["nodes"] if n["type"] == "sketch")
    assert sketch["props"]["geometry"][0]["geo_type"] == "line"


# --------------------------------------------------------------------------- #
# full + errors
# --------------------------------------------------------------------------- #
def test_full_equals_model_dump():
    doc = _hardware()
    assert project(doc, "full") == doc.model_dump(mode="json")


def test_unknown_level_raises():
    with pytest.raises(ValueError, match="projection"):
        project(_hardware(), "nonsense")


def test_levels_constant():
    assert PROJECTION_LEVELS == ("metadata", "topology", "geometry", "full")


# --------------------------------------------------------------------------- #
# projection_schema
# --------------------------------------------------------------------------- #
def test_projection_schema_describes_includes_and_excludes():
    schema = projection_schema("hardware", "topology")
    assert schema["domain"] == "hardware"
    assert schema["projection"] == "topology"
    assert isinstance(schema["includes"], list) and schema["includes"]
    assert isinstance(schema["excludes"], list) and schema["excludes"]
    assert isinstance(schema["description"], str) and schema["description"]


def test_projection_schema_unknown_domain_or_level_raises():
    with pytest.raises(ValueError):
        projection_schema("nope", "topology")
    with pytest.raises(ValueError):
        projection_schema("hardware", "nonsense")
