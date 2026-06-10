"""Token verification: dev HS256 and external JWKS RS256."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Any

import jwt

from forgelab.auth.config import AuthSettings
from forgelab.auth.models import ExpiredToken, InvalidToken, Principal


def issue_token(settings: AuthSettings, *, sub: str, client_id: str, scopes: Iterable[str]) -> str:
    """Sign an HS256 access token (used by the dev authorization server)."""
    now = int(time.time())
    payload = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": sub,
        "client_id": client_id,
        "scope": " ".join(sorted(scopes)),
        "iat": now,
        "exp": now + settings.access_token_ttl,
    }
    return jwt.encode(payload, settings.dev_secret, algorithm="HS256")


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    raw = claims.get("scope", "") or ""
    scopes = frozenset(raw.split()) if raw else frozenset()
    sub = claims.get("sub", "")
    return Principal(
        sub=sub,
        client_id=claims.get("client_id", sub),
        scopes=scopes,
        claims=claims,
    )


def _safe_decode(
    token: str, key: Any, algorithms: list[str], settings: AuthSettings
) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredToken("token has expired") from exc
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc


class TokenVerifier(ABC):
    @abstractmethod
    def verify(self, token: str) -> Principal: ...


class DevVerifier(TokenVerifier):
    """Validates HS256 tokens issued by the built-in dev authorization server."""

    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings

    def verify(self, token: str) -> Principal:
        claims = _safe_decode(token, self._settings.dev_secret, ["HS256"], self._settings)
        return principal_from_claims(claims)


class JwksVerifier(TokenVerifier):
    """Validates RS256 tokens against keys from an external IdP's JWKS.

    ``key_resolver`` maps a raw token to its signing key; the default builds a
    cached ``PyJWKClient`` from ``settings.jwks_url``. Tests inject a resolver to
    stay offline.
    """

    def __init__(
        self, settings: AuthSettings, key_resolver: Callable[[str], Any] | None = None
    ) -> None:
        self._settings = settings
        self._resolver = key_resolver or self._default_resolver(settings)

    @staticmethod
    def _default_resolver(settings: AuthSettings) -> Callable[[str], Any]:
        if not settings.jwks_url:
            raise ValueError("jwks_url is required for JwksVerifier in jwks mode")
        client = jwt.PyJWKClient(settings.jwks_url)
        return lambda token: client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> Principal:
        try:
            key = self._resolver(token)
        except jwt.PyJWTError as exc:
            raise InvalidToken(str(exc)) from exc
        claims = _safe_decode(token, key, ["RS256"], self._settings)
        return principal_from_claims(claims)


def build_verifier(settings: AuthSettings) -> TokenVerifier:
    if settings.mode == "jwks":
        return JwksVerifier(settings)
    return DevVerifier(settings)
