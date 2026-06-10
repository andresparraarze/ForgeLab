import asyncio

import pytest
from mcp.server.auth.provider import AccessToken

from forgelab.auth.config import AuthSettings
from forgelab.auth.verifier import issue_token
from forgelab.mcp import auth_bridge
from forgelab.mcp.auth_bridge import ForgeLabTokenVerifier, require_scope


def _settings():
    return AuthSettings(enabled=True, mode="dev", dev_secret="a" * 32)


def test_verify_token_maps_valid_dev_token():
    s = _settings()
    token = issue_token(s, sub="svc", client_id="svc", scopes={"forge:read", "forge:export"})
    access = asyncio.run(ForgeLabTokenVerifier(s).verify_token(token))
    assert access is not None
    assert access.client_id == "svc"
    assert access.subject == "svc"
    assert set(access.scopes) == {"forge:read", "forge:export"}


def test_verify_token_returns_none_for_garbage():
    access = asyncio.run(ForgeLabTokenVerifier(_settings()).verify_token("not-a-token"))
    assert access is None


def test_require_scope_allows_when_no_auth_context():
    assert require_scope("forge:read") is None


def test_require_scope_allows_when_scope_present(monkeypatch):
    monkeypatch.setattr(
        auth_bridge,
        "get_access_token",
        lambda: AccessToken(token="t", client_id="c", scopes=["forge:read", "forge:export"]),
    )
    assert require_scope("forge:export") is None


def test_require_scope_rejects_when_scope_missing(monkeypatch):
    monkeypatch.setattr(
        auth_bridge,
        "get_access_token",
        lambda: AccessToken(token="t", client_id="c", scopes=["forge:read"]),
    )
    with pytest.raises(PermissionError, match="missing required scope: forge:export"):
        require_scope("forge:export")
