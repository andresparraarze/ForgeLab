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


def _rsa_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return priv_pem, key.public_key()


def _jwks_settings():
    return AuthSettings(
        enabled=True,
        mode="jwks",
        issuer="https://idp.example",
        audience="forge-api",
        jwks_url="https://idp.example/jwks.json",
    )


def test_jwks_verifier_accepts_valid_rs256_token():
    from forgelab.auth.verifier import JwksVerifier

    priv, pub = _rsa_keypair()
    s = _jwks_settings()
    token = jwt.encode(
        {
            "iss": s.issuer,
            "aud": s.audience,
            "sub": "user-1",
            "scope": "forge:read",
            "exp": int(time.time()) + 60,
        },
        priv,
        algorithm="RS256",
    )
    verifier = JwksVerifier(s, key_resolver=lambda _tok: pub)
    principal = verifier.verify(token)
    assert principal.sub == "user-1"
    assert principal.scopes == frozenset({"forge:read"})


def test_jwks_verifier_rejects_token_signed_by_other_key():
    from forgelab.auth.verifier import JwksVerifier

    priv, _ = _rsa_keypair()
    _, other_pub = _rsa_keypair()
    s = _jwks_settings()
    token = jwt.encode(
        {"iss": s.issuer, "aud": s.audience, "sub": "u", "exp": int(time.time()) + 60},
        priv,
        algorithm="RS256",
    )
    with pytest.raises(InvalidToken):
        JwksVerifier(s, key_resolver=lambda _tok: other_pub).verify(token)


def test_build_verifier_selects_impl():
    from forgelab.auth.verifier import DevVerifier, JwksVerifier, build_verifier

    assert isinstance(build_verifier(AuthSettings(mode="dev")), DevVerifier)
    assert isinstance(build_verifier(_jwks_settings()), JwksVerifier)
