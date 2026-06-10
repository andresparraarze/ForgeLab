import time

import jwt
import pytest

from forgelab.auth.config import AuthSettings
from forgelab.auth.models import ExpiredToken, InvalidToken
from forgelab.auth.verifier import DevVerifier, issue_token


def _settings():
    return AuthSettings(enabled=True, mode="dev", dev_secret="a" * 32)


def test_dev_issue_and_verify_round_trip():
    s = _settings()
    token = issue_token(s, sub="svc", client_id="svc", scopes={"forge:read", "forge:export"})
    principal = DevVerifier(s).verify(token)
    assert principal.sub == "svc"
    assert principal.client_id == "svc"
    assert principal.scopes == frozenset({"forge:read", "forge:export"})


def test_tampered_token_rejected():
    s = _settings()
    token = issue_token(s, sub="svc", client_id="svc", scopes={"forge:read"})
    with pytest.raises(InvalidToken):
        DevVerifier(s).verify(token + "x")


def test_wrong_secret_rejected():
    token = issue_token(_settings(), sub="svc", client_id="svc", scopes=set())
    other = AuthSettings(enabled=True, mode="dev", dev_secret="b" * 32)
    with pytest.raises(InvalidToken):
        DevVerifier(other).verify(token)


def test_wrong_audience_rejected():
    s = _settings()
    bad = jwt.encode(
        {"iss": s.issuer, "aud": "someone-else", "sub": "x", "exp": int(time.time()) + 60},
        s.dev_secret,
        algorithm="HS256",
    )
    with pytest.raises(InvalidToken):
        DevVerifier(s).verify(bad)


def test_expired_token_rejected():
    s = _settings()
    expired = jwt.encode(
        {"iss": s.issuer, "aud": s.audience, "sub": "x", "exp": int(time.time()) - 10},
        s.dev_secret,
        algorithm="HS256",
    )
    with pytest.raises(ExpiredToken):
        DevVerifier(s).verify(expired)
