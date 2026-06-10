"""Auth configuration loaded from FORGELAB_AUTH_* environment variables."""

from __future__ import annotations

import secrets
from collections.abc import Mapping

from pydantic import BaseModel, Field


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


class AuthSettings(BaseModel):
    """Runtime auth settings. ``enabled=False`` (default) leaves everything open."""

    enabled: bool = False
    mode: str = "dev"  # "dev" (HS256, built-in issuer) | "jwks" (RS256, external IdP)
    issuer: str = "forgelab-dev"
    audience: str = "forgelab"
    dev_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    jwks_url: str | None = None
    access_token_ttl: int = 3600

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AuthSettings:
        secret = env.get("FORGELAB_AUTH_DEV_SECRET")
        return cls(
            enabled=_truthy(env.get("FORGELAB_AUTH_ENABLED", "false")),
            mode=env.get("FORGELAB_AUTH_MODE", "dev"),
            issuer=env.get("FORGELAB_AUTH_ISSUER", "forgelab-dev"),
            audience=env.get("FORGELAB_AUTH_AUDIENCE", "forgelab"),
            dev_secret=secret if secret else secrets.token_urlsafe(32),
            jwks_url=env.get("FORGELAB_AUTH_JWKS_URL") or None,
            access_token_ttl=int(env.get("FORGELAB_AUTH_TOKEN_TTL", "3600")),
        )
