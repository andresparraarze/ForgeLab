"""Bridge the MCP SDK's resource-server auth to forgelab.auth + per-tool scopes."""

from __future__ import annotations

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier

from forgelab.auth import AuthError, AuthSettings, build_verifier


class ForgeLabTokenVerifier(TokenVerifier):
    """Validate bearer tokens with forgelab.auth, returning the SDK's AccessToken."""

    def __init__(self, settings: AuthSettings) -> None:
        self._verifier = build_verifier(settings)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = self._verifier.verify(token)
        except AuthError:
            return None
        return AccessToken(
            token=token,
            client_id=principal.client_id,
            scopes=sorted(principal.scopes),
            subject=principal.sub,
            claims=dict(principal.claims),
        )


def require_scope(scope: str) -> None:
    """Enforce a scope for the current call.

    Over stdio (no auth) ``get_access_token()`` is ``None`` -> allowed. Over the
    authenticated HTTP transport a token is always present; raise if it lacks the
    required scope.
    """
    access = get_access_token()
    if access is None:
        return
    if scope not in access.scopes:
        raise PermissionError(f"missing required scope: {scope}")
