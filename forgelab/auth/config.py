"""Auth configuration loaded from FORGELAB_AUTH_* environment variables."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, Field


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


class AuthSettings(BaseModel):
    """Runtime auth settings. ``enabled=False`` (default) leaves everything open."""

    enabled: bool = False
    mode: Literal["dev", "jwks"] = "dev"  # "dev": HS256 built-in | "jwks": RS256 external IdP
    issuer: str = "forgelab-dev"
    audience: str = "forgelab"
    dev_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    jwks_url: str | None = None
    access_token_ttl: int = 3600

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        kwargs: dict[str, Any] = {}
        if "FORGELAB_AUTH_ENABLED" in env:
            kwargs["enabled"] = _truthy(env["FORGELAB_AUTH_ENABLED"])
        if "FORGELAB_AUTH_MODE" in env:
            kwargs["mode"] = env["FORGELAB_AUTH_MODE"]
        if "FORGELAB_AUTH_ISSUER" in env:
            kwargs["issuer"] = env["FORGELAB_AUTH_ISSUER"]
        if "FORGELAB_AUTH_AUDIENCE" in env:
            kwargs["audience"] = env["FORGELAB_AUTH_AUDIENCE"]
        secret = env.get("FORGELAB_AUTH_DEV_SECRET")
        if secret:
            kwargs["dev_secret"] = secret
        if url := env.get("FORGELAB_AUTH_JWKS_URL"):
            kwargs["jwks_url"] = url
        if ttl := env.get("FORGELAB_AUTH_TOKEN_TTL"):
            kwargs["access_token_ttl"] = int(ttl)
        return cls(**kwargs)
