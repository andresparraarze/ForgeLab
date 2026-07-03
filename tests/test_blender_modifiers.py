"""Blender modifier stack (subsurf/bevel/boolean/solidify) in the script exporter.

Objects describe organic geometry as primitives + modifiers; Blender's own
modifier evaluation computes the smooth result when the script runs. These
tests check the generated bpy calls, the boolean-target topological sort, and
the shipped organic_handle example.
"""

import ast
import json
import math
from pathlib import Path

import pytest

from forgelab.exporters.threed.blender_script import BlenderScriptExporter
from forgelab.spec import SPEC_VERSION, ForgeDocument

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples/threed/organic_handle.forge.json"


def _cube_positions() -> list[float]:
    pts = [(x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
    return [c for p in pts for c in p]


def _sphere_positions(radius: float = 1.0) -> list[float]:
    pts = []
    for i in range(1, 6):
        phi = math.pi * i / 6
        for j in range(8):
            a = 2 * math.pi * j / 8
            pts.append(
                (
                    radius * math.sin(phi) * math.cos(a),
                    radius * math.cos(phi),
                    radius * math.sin(phi) * math.sin(a),
                )
            )
    pts += [(0.0, radius, 0.0), (0.0, -radius, 0.0)]
    return [c for p in pts for c in p]


_IDENTITY = {
    "translation": [0.0, 0.0, 0.0],
    "rotation": [0.0, 0.0, 0.0, 1.0],
    "scale": [1.0, 1.0, 1.0],
}


def _object(node_id: str, mesh: str, modifiers: list[dict] | None = None) -> dict:
    props: dict = {"name": node_id, "transform": _IDENTITY, "mesh": mesh}
    if modifiers is not None:
        props["modifiers"] = modifiers
    return {"id": node_id, "type": "object", "props": props}


def _doc(*objects: dict) -> ForgeDocument:
    return ForgeDocument.model_validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": "threed",
            "meta": {"name": "mods", "generator": "test"},
            "nodes": [
                {
                    "id": "mesh_cube",
                    "type": "mesh",
                    "props": {"name": "Cube", "primitives": [{"positions": _cube_positions()}]},
                },
                {
                    "id": "mesh_ball",
                    "type": "mesh",
                    "props": {"name": "Ball", "primitives": [{"positions": _sphere_positions()}]},
                },
                *objects,
            ],
        }
    )


def _script(document: ForgeDocument) -> str:
    return BlenderScriptExporter().from_ir(document).decode()


def test_subsurf_modifier_code_generation():
    script = _script(
        _doc(_object("a", "mesh_cube", [{"type": "subsurf", "levels": 2, "render_levels": 3}]))
    )
    assert ".modifiers.new('Subsurf', 'SUBSURF')" in script
    assert "_mod.levels = 2" in script
    assert "_mod.render_levels = 3" in script


def test_subsurf_render_levels_default_to_levels():
    script = _script(_doc(_object("a", "mesh_cube", [{"type": "subsurf", "levels": 4}])))
    assert "_mod.levels = 4" in script
    assert "_mod.render_levels = 4" in script


def test_bevel_modifier_code_generation():
    script = _script(
        _doc(
            _object(
                "a",
                "mesh_cube",
                [{"type": "bevel", "width": 0.02, "segments": 3, "limit_method": "angle"}],
            )
        )
    )
    assert ".modifiers.new('Bevel', 'BEVEL')" in script
    assert "_mod.width = 0.02" in script
    assert "_mod.segments = 3" in script
    assert "_mod.limit_method = 'ANGLE'" in script


def test_solidify_modifier_code_generation():
    script = _script(_doc(_object("a", "mesh_cube", [{"type": "solidify", "thickness": 0.05}])))
    assert ".modifiers.new('Solidify', 'SOLIDIFY')" in script
    assert "_mod.thickness = 0.05" in script


def test_boolean_modifier_resolves_target_and_hides_it():
    script = _script(
        _doc(
            _object("cutter", "mesh_ball"),
            _object(
                "base",
                "mesh_cube",
                [{"type": "boolean", "operation": "difference", "target": "cutter"}],
            ),
        )
    )
    assert ".modifiers.new('Boolean', 'BOOLEAN')" in script
    assert "_mod.operation = 'DIFFERENCE'" in script
    # The target must be assigned to the bpy variable created for 'cutter',
    # and then hidden from render + viewport (the boolean consumes it).
    match = [ln for ln in script.splitlines() if ln.startswith("_mod.object = ")]
    assert len(match) == 1
    target_var = match[0].removeprefix("_mod.object = ")
    cutter_block = script[script.index("# object cutter") : script.index("# object base")]
    assert f"{target_var} = " in cutter_block
    assert f"{target_var}.hide_render = True" in script
    assert f"{target_var}.hide_set(True)" in script


def test_multiple_modifiers_apply_in_document_order():
    script = _script(
        _doc(
            _object("cutter", "mesh_ball"),
            _object(
                "base",
                "mesh_cube",
                [
                    {"type": "subsurf", "levels": 2},
                    {"type": "bevel", "width": 0.02},
                    {"type": "boolean", "operation": "difference", "target": "cutter"},
                    {"type": "solidify", "thickness": 0.03},
                ],
            ),
        )
    )
    order = [
        script.index(".modifiers.new('Subsurf', 'SUBSURF')"),
        script.index(".modifiers.new('Bevel', 'BEVEL')"),
        script.index(".modifiers.new('Boolean', 'BOOLEAN')"),
        script.index(".modifiers.new('Solidify', 'SOLIDIFY')"),
    ]
    assert order == sorted(order)


def test_topological_sort_orders_a_boolean_dependency_chain():
    # a cuts with b, b cuts with c; document order is a, b, c but the script
    # must create c, then b, then a.
    script = _script(
        _doc(
            _object("a", "mesh_cube", [{"type": "boolean", "target": "b"}]),
            _object("b", "mesh_cube", [{"type": "boolean", "target": "c"}]),
            _object("c", "mesh_ball"),
        )
    )
    assert script.index("# object c") < script.index("# object b") < script.index("# object a")


def test_topological_sort_raises_clearly_on_a_cycle():
    doc = _doc(
        _object("a", "mesh_cube", [{"type": "boolean", "target": "b"}]),
        _object("b", "mesh_cube", [{"type": "boolean", "target": "a"}]),
    )
    with pytest.raises(ValueError, match="cycle.*a -> b -> a|cycle.*b -> a -> b"):
        BlenderScriptExporter().from_ir(doc)


def test_unknown_boolean_target_raises():
    doc = _doc(_object("a", "mesh_cube", [{"type": "boolean", "target": "ghost"}]))
    with pytest.raises(ValueError, match="ghost"):
        BlenderScriptExporter().from_ir(doc)


def test_modifiers_on_meshless_object_raise():
    doc = _doc(_object("a", "", [{"type": "subsurf"}]))
    with pytest.raises(ValueError, match="no mesh"):
        BlenderScriptExporter().from_ir(doc)


def test_generated_script_with_modifiers_is_valid_python():
    script = _script(
        _doc(
            _object("cutter", "mesh_ball"),
            _object(
                "base",
                "mesh_cube",
                [
                    {"type": "subsurf", "levels": 2, "render_levels": 3},
                    {"type": "bevel", "width": 0.02, "segments": 3},
                    {"type": "boolean", "operation": "difference", "target": "cutter"},
                    {"type": "solidify", "thickness": 0.02},
                ],
            ),
        )
    )
    ast.parse(script)


def test_organic_handle_example_produces_a_valid_script():
    document = ForgeDocument.model_validate(json.loads(_EXAMPLE.read_text()))
    script = BlenderScriptExporter().from_ir(document).decode()
    ast.parse(script)
    # cylinder primitive + subsurf + bevel, boolean thumb-rest cut, and the
    # cutter object created before the handle that references it.
    assert "bpy.ops.mesh.primitive_cylinder_add" in script
    assert ".modifiers.new('Subsurf', 'SUBSURF')" in script
    assert ".modifiers.new('Bevel', 'BEVEL')" in script
    assert "_mod.operation = 'DIFFERENCE'" in script
    assert script.index("# object thumb_cutter") < script.index("# object handle")
