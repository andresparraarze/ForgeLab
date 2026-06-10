"""ForgeLab MCP tool callables.

Plain functions wrapping the core compiler, registry, and AI SDK. ``server.py``
registers them with FastMCP. Each enforces its scope via ``require_scope`` (a
no-op over the unauthenticated stdio transport).
"""

from __future__ import annotations

import os
from typing import Any

from forgelab.core import UnknownToolError, default_registry, validate
from forgelab.mcp.auth_bridge import require_scope
from forgelab.mcp.content import decode_content, encode_bytes
from forgelab.sdk import DOMAIN_VOCAB, ForgeAgent, domain_schema, few_shot, system_prompt

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


def export_document(document: dict[str, Any], tool: str) -> dict[str, Any]:
    """Export a ForgeLab document to a format tool's native file.

    Returns {"tool", "encoding": "utf-8"|"base64", "content": <str>}.
    """
    require_scope("forge:export")
    try:
        doc = validate(document)
    except Exception as exc:
        raise ValueError(f"invalid document: {exc}") from exc
    try:
        exporter = _registry.get_exporter(tool)
    except UnknownToolError as exc:
        raise ValueError(str(exc)) from exc
    try:
        data = exporter().from_ir(doc)
    except NotImplementedError as exc:
        raise ValueError(f"export not implemented for {tool!r}: {exc}") from exc
    return {"tool": tool, **encode_bytes(data)}


def import_file(tool: str, content: str, encoding: str = "utf-8") -> dict[str, Any]:
    """Import a format tool's native file into a ForgeLab document (as a dict)."""
    require_scope("forge:export")
    try:
        importer = _registry.get_importer(tool)
    except UnknownToolError as exc:
        raise ValueError(str(exc)) from exc
    source = decode_content(content, encoding)
    document = importer().to_ir(source)
    return document.model_dump(mode="json")


def _make_agent(model: str) -> ForgeAgent:
    """Construct a ForgeAgent. Indirection so tests can inject a fake agent."""
    return ForgeAgent(model=model)


def generate_document(prompt: str, domain: str, model: str = "claude-opus-4-8") -> dict[str, Any]:
    """Generate a validated ForgeLab document from a natural-language prompt."""
    require_scope("forge:generate")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("generation unavailable: ANTHROPIC_API_KEY is not set on the server")
    try:
        agent = _make_agent(model)
    except ImportError as exc:
        raise ValueError(
            'generation unavailable: install the agent extra (pip install "forgelab[agent]")'
        ) from exc
    document = agent.design(prompt, domain=domain)
    return document.model_dump(mode="json")
