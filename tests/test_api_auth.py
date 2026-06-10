from fastapi.testclient import TestClient

from forgelab.api.app import app
from forgelab.auth.config import AuthSettings
from forgelab.auth.fastapi import get_auth_settings
from forgelab.spec import SPEC_VERSION


def _doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def _enable_auth():
    app.dependency_overrides[get_auth_settings] = lambda: AuthSettings(
        enabled=True, mode="dev", dev_secret="a" * 32
    )


def teardown_function():
    app.dependency_overrides.clear()


def test_health_and_spec_public_even_when_enabled():
    _enable_auth()
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    assert c.get("/spec").status_code == 200


def test_validate_requires_token_when_enabled():
    _enable_auth()
    c = TestClient(app)
    assert c.post("/validate", json=_doc()).status_code == 401


def test_validate_works_with_token():
    _enable_auth()
    c = TestClient(app)
    tok = c.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "forgelab-dev",
            "client_secret": "forgelab-dev-secret",
            "scope": "forge:read",
        },
    ).json()["access_token"]
    r = c.post("/validate", json=_doc(), headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_export_requires_export_scope():
    _enable_auth()
    c = TestClient(app)
    tok = c.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "forgelab-dev",
            "client_secret": "forgelab-dev-secret",
            "scope": "forge:read",  # not forge:export
        },
    ).json()["access_token"]
    r = c.post("/export/kicad", json=_doc(), headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
