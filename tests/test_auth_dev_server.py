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


def _authorize_and_get_code(c, *, challenge, scope="forge:read", state="xyz"):
    r = c.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "svc",
            "redirect_uri": "https://app/cb",
            "scope": scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith("https://app/cb?")
    assert f"state={state}" in location
    code = location.split("code=")[1].split("&")[0]
    return code


def test_authorization_code_pkce_happy_path():
    from forgelab.auth.dev_server import s256_challenge

    c = _client()
    verifier = "verifier-1234567890-abcdefghijklmnop"
    code = _authorize_and_get_code(c, challenge=s256_challenge(verifier))
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "svc",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": "https://app/cb",
        },
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "forge:read"


def test_authorization_code_bad_verifier_rejected():
    from forgelab.auth.dev_server import s256_challenge

    c = _client()
    code = _authorize_and_get_code(c, challenge=s256_challenge("the-real-verifier-aaaaaaaa"))
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "svc",
            "code": code,
            "code_verifier": "the-wrong-verifier-bbbbbbbb",
            "redirect_uri": "https://app/cb",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_authorization_code_is_single_use():
    from forgelab.auth.dev_server import s256_challenge

    c = _client()
    verifier = "verifier-1234567890-abcdefghijklmnop"
    code = _authorize_and_get_code(c, challenge=s256_challenge(verifier))
    data = {
        "grant_type": "authorization_code",
        "client_id": "svc",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": "https://app/cb",
    }
    assert c.post("/oauth/token", data=data).status_code == 200
    assert c.post("/oauth/token", data=data).status_code == 400


def test_authorize_rejects_unknown_redirect_uri():
    c = _client()
    r = c.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "svc",
            "redirect_uri": "https://evil/cb",
            "scope": "forge:read",
            "state": "s",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_authorize_percent_encodes_state():
    c = _client()
    r = c.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "svc",
            "redirect_uri": "https://app/cb",
            "scope": "forge:read",
            "state": "a&b=c",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 307
    loc = r.headers["location"]
    assert "state=a%26b%3Dc" in loc
    # the raw, unencoded form must NOT appear
    assert "state=a&b=c" not in loc


def test_authorization_code_expired_rejected():
    import time as _time

    from forgelab.auth.dev_server import _PendingCode, s256_challenge

    settings = AuthSettings(enabled=True, mode="dev", dev_secret="a" * 32)
    store = DevClientStore()
    store.add(
        DevClient(
            client_id="svc",
            client_secret="sekret",
            allowed_scopes=frozenset({"forge:read"}),
            redirect_uris=("https://app/cb",),
        )
    )
    verifier = "verifier-1234567890-abcdefghijklmnop"
    store.put_code(
        "expired",
        _PendingCode(
            client_id="svc",
            scopes=frozenset({"forge:read"}),
            code_challenge=s256_challenge(verifier),
            redirect_uri="https://app/cb",
            expires_at=_time.time() - 1,
        ),
    )
    app = FastAPI()
    app.include_router(create_dev_auth_router(lambda: settings, lambda: store))
    c = TestClient(app)
    r = c.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "svc",
            "code": "expired",
            "code_verifier": verifier,
            "redirect_uri": "https://app/cb",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_unsupported_grant_type_rejected():
    c = _client()
    r = c.post("/oauth/token", data={"grant_type": "password", "client_id": "svc"})
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


def test_authorize_rejects_plain_pkce_method():
    c = _client()
    r = c.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "svc",
            "redirect_uri": "https://app/cb",
            "scope": "forge:read",
            "state": "s",
            "code_challenge": "abc",
            "code_challenge_method": "plain",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
