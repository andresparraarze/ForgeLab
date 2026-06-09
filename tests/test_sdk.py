from forgelab.sdk import dump, load, new_document
from forgelab.spec import SPEC_VERSION, Domain, ForgeDocument


def test_new_document_stamps_version():
    doc = new_document(domain="hardware", name="blinky")
    assert isinstance(doc, ForgeDocument)
    assert doc.forgelab_version == SPEC_VERSION
    assert doc.domain == Domain.HARDWARE
    assert doc.meta.name == "blinky"


def test_dump_then_load_roundtrips():
    doc = new_document(domain="threed", name="scene")
    text = dump(doc)
    assert isinstance(text, str)
    restored = load(text)
    assert restored == doc
