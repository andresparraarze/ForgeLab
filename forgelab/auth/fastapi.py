"""FastAPI integration for ForgeLab auth (the only module importing FastAPI)."""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from forgelab.auth.config import AuthSettings
from forgelab.auth.dev_server import DevClient, DevClientStore, create_dev_auth_router
from forgelab.auth.models import AuthError, InsufficientScope, InvalidToken, Principal
from forgelab.auth.verifier import TokenVerifier, build_verifier

__all__ = [
    "get_auth_settings",
    "get_client_store",
    "require_auth",
    "install_auth_error_handler",
    "mount_dev_auth",
]

_ALL_SCOPES = frozenset({"forge:read", "forge:export", "forge:generate"})
_ANONYMOUS = Principal(sub="anonymous", client_id="anonymous", scopes=frozenset())

_settings: AuthSettings | None = None
_store: DevClientStore | None = None
_verifiers: dict[tuple[str, str, str, str | None, str], TokenVerifier] = {}


def _verifier_for(settings: AuthSettings) -> TokenVerifier:
    """Return a cached verifier for these settings (reuses the JWKS key cache)."""
    key = (
        settings.mode,
        settings.issuer,
        settings.audience,
        settings.jwks_url,
        settings.dev_secret,
    )
    verifier = _verifiers.get(key)
    if verifier is None:
        verifier = build_verifier(settings)
        _verifiers[key] = verifier
    return verifier


def get_auth_settings() -> AuthSettings:
    """Process-wide settings from env (overridable via app.dependency_overrides).

    Resolved once per process on first use; changing FORGELAB_AUTH_* env vars
    requires a restart. Tests override this via app.dependency_overrides.
    """
    global _settings
    if _settings is None:
        _settings = AuthSettings.from_env(os.environ)
    return _settings


def get_client_store() -> DevClientStore:
    """Default in-memory client store, seeded with one dev client from env.

    Resolved once per process on first use; requires a restart to pick up new env values.
    """
    global _store
    if _store is None:
        store = DevClientStore()
        store.add(
            DevClient(
                client_id=os.environ.get("FORGELAB_AUTH_DEV_CLIENT_ID", "forgelab-dev"),
                client_secret=os.environ.get(
                    "FORGELAB_AUTH_DEV_CLIENT_SECRET", "forgelab-dev-secret"
                ),
                allowed_scopes=_ALL_SCOPES,
                redirect_uris=tuple(
                    u for u in os.environ.get("FORGELAB_AUTH_DEV_REDIRECT_URIS", "").split(",") if u
                ),
            )
        )
        _store = store
    return _store


def require_auth(*required_scopes: str):
    """Dependency factory enforcing a bearer token carrying every given scope."""

    def dependency(
        request: Request,
        settings: AuthSettings = Depends(get_auth_settings),  # noqa: B008
    ) -> Principal:
        if not settings.enabled:
            return _ANONYMOUS
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise InvalidToken("missing or malformed Authorization header")
        principal = _verifier_for(settings).verify(token)
        if not set(required_scopes).issubset(principal.scopes):
            raise InsufficientScope(required_scopes)
        return principal

    return dependency


def install_auth_error_handler(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def _handle(_request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error_code, "error_description": exc.description},
            headers={"WWW-Authenticate": exc.www_authenticate()},
        )


def mount_dev_auth(app: FastAPI) -> None:
    """Install the error handler + dev authorization-server router on an app."""
    install_auth_error_handler(app)
    app.include_router(create_dev_auth_router(get_auth_settings, get_client_store))
