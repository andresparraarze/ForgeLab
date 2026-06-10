"""Auth principals and the error hierarchy mapped to OAuth bearer responses."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Principal:
    """An authenticated caller."""

    sub: str
    client_id: str
    scopes: frozenset[str]
    claims: dict[str, Any] = field(default_factory=dict)


class AuthError(Exception):
    """Base for auth failures; maps to an HTTP status + WWW-Authenticate header."""

    error_code = "invalid_token"
    status_code = 401

    def __init__(self, description: str) -> None:
        self.description = description
        super().__init__(description)

    def www_authenticate(self) -> str:
        return f'Bearer error="{self.error_code}", error_description="{self.description}"'


class InvalidToken(AuthError):
    """Missing, malformed, or unverifiable token."""


class ExpiredToken(AuthError):
    """Token signature valid but past its expiry."""


class InsufficientScope(AuthError):
    error_code = "insufficient_scope"
    status_code = 403

    def __init__(self, needed: Iterable[str]) -> None:
        self.needed = tuple(needed)
        super().__init__(f"requires scope(s): {' '.join(self.needed)}")

    def www_authenticate(self) -> str:
        return f'Bearer error="{self.error_code}", scope="{" ".join(self.needed)}"'
