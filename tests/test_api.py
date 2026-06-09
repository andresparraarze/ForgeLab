from fastapi.testclient import TestClient

from forgelab.api.app import app
from forgelab.spec import SPEC_VERSION

client = TestClient(app)


def _valid_doc_dict():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["spec_version"] == SPEC_VERSION


def test_spec_returns_schema():
    r = client.get("/spec")
    assert r.status_code == 200
    assert r.json()["title"] == "ForgeDocument"


def test_validate_accepts_valid_document():
    r = client.post("/validate", json=_valid_doc_dict())
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_validate_rejects_bad_version():
    data = _valid_doc_dict()
    data["forgelab_version"] = "999.0.0"
    r = client.post("/validate", json=data)
    assert r.status_code == 400
    assert "valid" in r.json()
    assert r.json()["valid"] is False
