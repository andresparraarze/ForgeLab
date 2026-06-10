"""Shared OAuth 2.0 auth for ForgeLab (REST API + future MCP server).

Domain-agnostic: imports nothing from forgelab.{core,spec,formats,importers,
exporters,sdk}. Only ``forgelab.auth.fastapi`` imports FastAPI.
"""

from forgelab.auth.config import AuthSettings
from forgelab.auth.models import (
    AuthError,
    ExpiredToken,
    InsufficientScope,
    InvalidToken,
    Principal,
)
from forgelab.auth.verifier import (
    DevVerifier,
    JwksVerifier,
    TokenVerifier,
    build_verifier,
)

__all__ = [
    "AuthSettings",
    "AuthError",
    "ExpiredToken",
    "InsufficientScope",
    "InvalidToken",
    "Principal",
    "DevVerifier",
    "JwksVerifier",
    "TokenVerifier",
    "build_verifier",
]
