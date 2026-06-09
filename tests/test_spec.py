import pytest
from pydantic import ValidationError

from forgelab.spec.models import Domain, ForgeDocument, Node
from forgelab.spec.version import SPEC_VERSION, is_compatible


def test_spec_version_is_semver_string():
    assert isinstance(SPEC_VERSION, str)
    parts = SPEC_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_same_major_is_compatible():
    major = SPEC_VERSION.split(".")[0]
    assert is_compatible(f"{major}.0.0") is True


def test_different_major_is_incompatible():
    assert is_compatible("999.0.0") is False


def test_malformed_version_is_incompatible():
    assert is_compatible("not-a-version") is False


def _valid_doc_dict():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [
            {"id": "r1", "type": "component", "props": {"value": "330R"}, "children": []}
        ],
    }


def test_valid_document_parses():
    doc = ForgeDocument.model_validate(_valid_doc_dict())
    assert doc.forgelab_version == SPEC_VERSION
    assert doc.domain == Domain.HARDWARE
    assert doc.nodes[0].id == "r1"


def test_document_requires_forgelab_version():
    data = _valid_doc_dict()
    del data["forgelab_version"]
    with pytest.raises(ValidationError):
        ForgeDocument.model_validate(data)


def test_unknown_domain_rejected():
    data = _valid_doc_dict()
    data["domain"] = "quantum"
    with pytest.raises(ValidationError):
        ForgeDocument.model_validate(data)


def test_node_children_nest():
    node = Node.model_validate(
        {"id": "p", "type": "group", "children": [{"id": "c", "type": "component"}]}
    )
    assert node.children[0].id == "c"
