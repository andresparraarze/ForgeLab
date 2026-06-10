from fastapi import FastAPI
from fastapi.testclient import TestClient

from forgelab.auth.config import AuthSettings
from forgelab.auth.dev_server import DevClient, DevClientStore, create_dev_auth_router


def _client(mode="dev"):
    settings = AuthSettings(enabled=True, mode=mode, dev_secret="a" * 32)
    store = DevClientStore()
    store.add(
        DevClient(
            client_id="svc",
            client_secret="sekret",
            allowed_scopes=frozenset({"forge:read", "forge:export"}),
            redirect_uris=("https://app/cb",),
        )
    )
    app = FastAPI()
    app.include_router(create_dev_auth_router(lambda: settings, lambda: store))
    return TestClient(app)


def test_client_credentials_issues_token():
    c = _client()
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "svc",
            "client_secret": "sekret",
            "scope": "forge:read",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "forge:read"
    assert body["access_token"]


def test_client_credentials_bad_secret_rejected():
    c = _client()
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "svc",
            "client_secret": "wrong",
            "scope": "forge:read",
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_client"


def test_scope_is_intersected_with_allowed():
    c = _client()
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "svc",
            "client_secret": "sekret",
            "scope": "forge:read forge:generate",  # generate not allowed
        },
    )
    assert r.status_code == 200
    assert set(r.json()["scope"].split()) == {"forge:read"}


def test_discovery_document():
    c = _client()
    r = c.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    meta = r.json()
    assert meta["token_endpoint"].endswith("/oauth/token")
    assert "client_credentials" in meta["grant_types_supported"]
    assert meta["code_challenge_methods_supported"] == ["S256"]


def test_endpoints_404_when_not_dev_mode():
    c = _client(mode="jwks")
    r = c.post("/oauth/token", data={"grant_type": "client_credentials"})
    assert r.status_code == 404
