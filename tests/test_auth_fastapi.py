from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from forgelab.auth.config import AuthSettings
from forgelab.auth.dev_server import DevClient, DevClientStore, create_dev_auth_router
from forgelab.auth.fastapi import (
    get_auth_settings,
    get_client_store,
    install_auth_error_handler,
    require_auth,
)
from forgelab.auth.models import Principal


def _make_app(settings: AuthSettings):
    store = DevClientStore()
    store.add(
        DevClient(
            client_id="svc",
            client_secret="sekret",
            allowed_scopes=frozenset({"forge:read", "forge:export"}),
            redirect_uris=(),
        )
    )
    app = FastAPI()
    install_auth_error_handler(app)
    app.dependency_overrides[get_auth_settings] = lambda: settings
    app.dependency_overrides[get_client_store] = lambda: store
    app.include_router(create_dev_auth_router(lambda: settings, lambda: store))

    @app.get("/read")
    def read(p: Principal = Depends(require_auth("forge:read"))):  # noqa: B008
        return {"sub": p.sub}

    return TestClient(app)


def _token(client, scope):
    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "svc",
            "client_secret": "sekret",
            "scope": scope,
        },
    )
    return r.json()["access_token"]


def test_open_when_disabled():
    c = _make_app(AuthSettings(enabled=False, dev_secret="a" * 32))
    assert c.get("/read").status_code == 200


def test_missing_token_401():
    c = _make_app(AuthSettings(enabled=True, dev_secret="a" * 32))
    r = c.get("/read")
    assert r.status_code == 401
    assert "Bearer" in r.headers["www-authenticate"]


def test_valid_token_200():
    settings = AuthSettings(enabled=True, dev_secret="a" * 32)
    c = _make_app(settings)
    token = _token(c, "forge:read")
    r = c.get("/read", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["sub"] == "svc"


def test_insufficient_scope_403():
    settings = AuthSettings(enabled=True, dev_secret="a" * 32)
    c = _make_app(settings)
    token = _token(c, "forge:export")  # lacks forge:read
    r = c.get("/read", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert "insufficient_scope" in r.headers["www-authenticate"]
