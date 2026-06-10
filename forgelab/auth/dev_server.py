"""Built-in, in-memory dev authorization server (dev mode only).

Exists so the repository runs standalone with no external IdP. Not for
production: tokens and codes live in memory only.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from forgelab.auth.config import AuthSettings
from forgelab.auth.verifier import issue_token


@dataclass(frozen=True)
class DevClient:
    client_id: str
    client_secret: str
    allowed_scopes: frozenset[str]
    redirect_uris: tuple[str, ...] = ()


@dataclass
class _PendingCode:
    client_id: str
    scopes: frozenset[str]
    code_challenge: str
    redirect_uri: str
    expires_at: float


class DevClientStore:
    """In-memory client registry + single-use authorization codes."""

    def __init__(self) -> None:
        self._clients: dict[str, DevClient] = {}
        self._codes: dict[str, _PendingCode] = {}

    def add(self, client: DevClient) -> None:
        self._clients[client.client_id] = client

    def get(self, client_id: str) -> DevClient | None:
        return self._clients.get(client_id)

    def put_code(self, code: str, pending: _PendingCode) -> None:
        self._codes[code] = pending

    def pop_code(self, code: str) -> _PendingCode | None:
        return self._codes.pop(code, None)


def s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _intersect(requested: str, allowed: frozenset[str]) -> frozenset[str]:
    if not requested:
        return allowed
    return frozenset(requested.split()) & allowed


def create_dev_auth_router(
    get_settings: Callable[[], AuthSettings],
    get_store: Callable[[], DevClientStore],
) -> APIRouter:
    router = APIRouter()

    def _require_dev(settings: AuthSettings) -> None:
        if settings.mode != "dev":
            raise HTTPException(status_code=404, detail="dev auth server is disabled")

    @router.get("/.well-known/oauth-authorization-server")
    def metadata(
        request: Request,
        settings: AuthSettings = Depends(get_settings),  # noqa: B008
    ) -> dict:
        _require_dev(settings)
        base = str(request.base_url).rstrip("/")
        return {
            "issuer": settings.issuer,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "grant_types_supported": ["client_credentials", "authorization_code"],
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["forge:read", "forge:export", "forge:generate"],
        }

    @router.post("/oauth/token")
    def token(
        grant_type: str = Form(...),
        client_id: str = Form(""),
        client_secret: str = Form(""),
        scope: str = Form(""),
        code: str = Form(""),
        code_verifier: str = Form(""),
        redirect_uri: str = Form(""),
        settings: AuthSettings = Depends(get_settings),  # noqa: B008
        store: DevClientStore = Depends(get_store),  # noqa: B008
    ) -> JSONResponse:
        _require_dev(settings)
        if grant_type == "client_credentials":
            return _client_credentials(settings, store, client_id, client_secret, scope)
        if grant_type == "authorization_code":
            return _authorization_code(
                settings, store, client_id, code, code_verifier, redirect_uri
            )
        return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})

    def _client_credentials(
        settings: AuthSettings,
        store: DevClientStore,
        client_id: str,
        client_secret: str,
        scope: str,
    ) -> JSONResponse:
        client = store.get(client_id)
        if client is None or not secrets.compare_digest(client.client_secret, client_secret):
            return JSONResponse(status_code=401, content={"error": "invalid_client"})
        granted = _intersect(scope, client.allowed_scopes)
        access = issue_token(settings, sub=client_id, client_id=client_id, scopes=granted)
        return JSONResponse(
            content={
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": settings.access_token_ttl,
                "scope": " ".join(sorted(granted)),
            }
        )

    def _authorization_code(
        settings: AuthSettings,
        store: DevClientStore,
        client_id: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> JSONResponse:
        # Real implementation (PKCE) lands in Task 6.
        return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})

    return router
