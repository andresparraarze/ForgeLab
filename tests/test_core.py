import pytest
from pydantic import ValidationError

from forgelab.core import IncompatibleVersionError, validate
from forgelab.spec import SPEC_VERSION, ForgeDocument


def _valid_doc_dict():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def test_validate_returns_forge_document():
    doc = validate(_valid_doc_dict())
    assert isinstance(doc, ForgeDocument)
    assert doc.meta.name == "blinky"


def test_validate_rejects_incompatible_version():
    data = _valid_doc_dict()
    data["forgelab_version"] = "999.0.0"
    with pytest.raises(IncompatibleVersionError):
        validate(data)


def test_validate_rejects_malformed_document():
    with pytest.raises(ValidationError):
        validate({"forgelab_version": SPEC_VERSION})  # missing domain/meta
