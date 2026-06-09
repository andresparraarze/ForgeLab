from forgelab.core import validate
from forgelab.core.pipeline import default_registry, transform
from forgelab.spec import SPEC_VERSION


def _valid_doc_dict():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def test_default_registry_has_kicad_importer():
    reg = default_registry()
    assert reg.get_importer("kicad").tool_name == "kicad"
    assert reg.get_exporter("blender").tool_name == "blender"


def test_transform_is_identity_by_default():
    doc = validate(_valid_doc_dict())
    out = transform(doc, passes=[])
    assert out == doc
