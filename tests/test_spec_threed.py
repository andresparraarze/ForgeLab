import pytest
from pydantic import ValidationError

from forgelab.spec import (
    NODE_MATERIAL,
    NODE_MESH,
    NODE_OBJECT,
    NODE_SCENE,
    Material,
    Mesh,
    Object3D,
    Primitive,
    Transform,
)


def test_node_type_constants():
    assert NODE_SCENE == "scene"
    assert NODE_OBJECT == "object"
    assert NODE_MESH == "mesh"
    assert NODE_MATERIAL == "material"


def test_material_defaults():
    m = Material(name="Red", base_color=[0.8, 0.1, 0.1, 1.0])
    assert m.metallic == 1.0
    assert m.roughness == 1.0


def test_material_base_color_must_be_rgba():
    with pytest.raises(ValidationError):
        Material(name="bad", base_color=[1.0, 0.0, 0.0])


def test_transform_length_validators():
    t = Transform(translation=[0, 0, 0], rotation=[0, 0, 0, 1], scale=[1, 1, 1])
    assert t.rotation == [0, 0, 0, 1]
    with pytest.raises(ValidationError):
        Transform(translation=[0, 0], rotation=[0, 0, 0, 1], scale=[1, 1, 1])
    with pytest.raises(ValidationError):
        Transform(translation=[0, 0, 0], rotation=[0, 0, 0], scale=[1, 1, 1])


def test_primitive_and_mesh_roundtrip_through_dict():
    prim = Primitive(positions=[0.0, 0.0, 0.0], indices=[0], material="Red")
    mesh = Mesh(name="CubeMesh", primitives=[prim])
    restored = Mesh.model_validate(mesh.model_dump())
    assert restored == mesh


def test_object_defaults_to_no_mesh():
    obj = Object3D(
        name="Empty",
        transform=Transform(translation=[0, 0, 0], rotation=[0, 0, 0, 1], scale=[1, 1, 1]),
    )
    assert obj.mesh == ""


def test_models_forbid_extra_fields():
    with pytest.raises(ValidationError):
        Material(name="x", base_color=[1, 1, 1, 1], bogus=1)


def test_scene_model_validates_name():
    from forgelab.spec import Scene

    scene = Scene.model_validate({"name": "Scene"})
    assert scene.name == "Scene"


def test_scene_model_forbids_extra():
    import pytest
    from pydantic import ValidationError

    from forgelab.spec import Scene

    with pytest.raises(ValidationError):
        Scene.model_validate({"name": "Scene", "bogus": 1})
