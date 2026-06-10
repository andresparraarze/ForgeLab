"""ForgeLab MCP tool callables.

Plain functions wrapping the core compiler, registry, and AI SDK. ``server.py``
registers them with FastMCP. Each enforces its scope via ``require_scope`` (a
no-op over the unauthenticated stdio transport).
"""

from __future__ import annotations

from typing import Any

from forgelab.core import default_registry, validate
from forgelab.mcp.auth_bridge import require_scope
from forgelab.sdk import DOMAIN_VOCAB, domain_schema, few_shot, system_prompt

_registry = default_registry()


def validate_document(document: dict[str, Any]) -> dict[str, Any]:
    """Validate a ForgeLab document. Returns {"valid": bool, "error"?: str}."""
    require_scope("forge:read")
    try:
        validate(document)
    except Exception as exc:  # any validation failure is reported to the caller
        return {"valid": False, "error": str(exc)}
    return {"valid": True}


def get_domain_schema(domain: str) -> dict[str, Any]:
    """Return the JSON Schema for a ForgeLab domain."""
    require_scope("forge:read")
    try:
        return domain_schema(domain)
    except KeyError as exc:
        raise ValueError(f"unknown domain: {domain!r}") from exc


def get_prompt(domain: str) -> dict[str, Any]:
    """Return the system prompt and a few-shot example for a domain."""
    require_scope("forge:read")
    try:
        return {"system": system_prompt(domain), "few_shot": few_shot(domain)}
    except KeyError as exc:
        raise ValueError(f"unknown domain: {domain!r}") from exc


def list_domains() -> list[str]:
    """List the ForgeLab domains the server understands."""
    require_scope("forge:read")
    return sorted(DOMAIN_VOCAB)


def list_formats() -> dict[str, dict[str, bool]]:
    """List registered format tools and their import/export availability."""
    require_scope("forge:read")
    return _registry.tool_names()
