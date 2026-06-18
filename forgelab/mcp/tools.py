"""ForgeLab MCP tool callables.

Plain functions wrapping the core compiler, registry, and AI SDK. ``server.py``
registers them with FastMCP. Each enforces its scope via ``require_scope`` (a
no-op over the unauthenticated stdio transport).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

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


def _agent_extra_installed() -> bool:
    """True if the Anthropic SDK (the ``agent`` extra) is importable."""
    try:
        import anthropic  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _generation_availability() -> tuple[bool, str | None]:
    """Whether ``generate_document`` can run, and if not, why.

    Generation needs both ``ANTHROPIC_API_KEY`` set on the server and the
    ``agent`` extra installed. Returns ``(available, reason)`` where ``reason``
    is ``None`` when available.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY is not set on the server"
    if not _agent_extra_installed():
        return False, 'the agent extra is not installed (pip install "forgelab[agent]")'
    return True, None


def generation_status() -> dict[str, Any]:
    """Report whether ``generate_document`` is currently usable on this server.

    Call this before ``generate_document`` to avoid a wasted round trip: when
    generation is unavailable (no API key, or the agent extra is not installed),
    skip ``generate_document`` and build the document yourself against the schema
    instead. Returns ``{"available": bool}``; when unavailable, also ``"reason"``
    and an ``"alternative"`` describing how to proceed without generation.
    """
    require_scope("forge:read")
    available, reason = _generation_availability()
    if available:
        return {"available": True}
    return {
        "available": False,
        "reason": reason,
        "alternative": (
            "Build the document yourself: call get_domain_schema and get_prompt "
            "for the domain, construct the complete document in one pass, then "
            "call validate_document once."
        ),
    }


def _resolve_output_path(output_path: str) -> Path:
    """Bare filenames land in FORGELAB_OUTPUT_DIR (or the cwd); paths pass through."""
    path = Path(output_path)
    if not path.is_absolute() and path.parent == Path("."):
        base = os.environ.get("FORGELAB_OUTPUT_DIR")
        return (Path(base) if base else Path.cwd()) / path
    return path


def export_document(
    document: dict[str, Any], tool: str, output_path: str | None = None
) -> dict[str, Any]:
    """Export a ForgeLab document to a format tool's native file.

    Without ``output_path``, returns the file inline:
    {"tool", "encoding": "utf-8"|"base64", "content": <str>}.

    With ``output_path``, writes the file to disk and returns
    {"tool", "path", "bytes_written"} so another tool (e.g. a KiCad or Blender
    MCP server) can open it directly.

    output_path: Prefer a bare filename (e.g. "castle.gltf") so the file is
    written to the configured FORGELAB_OUTPUT_DIR. Only pass an absolute path if
    you need to write somewhere else. A bare filename is written into
    ``FORGELAB_OUTPUT_DIR`` when set, else the current working directory.
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
    except ValidationError as exc:
        # The IR validator is lenient about node props; exporters re-validate
        # them strictly against the domain models.
        raise ValueError(f"export failed for {tool!r}: document props are invalid: {exc}") from exc
    except ValueError as exc:
        # Exporters raise ValueError for actionable problems (e.g. a reference
        # that names a node by display name instead of its id).
        raise ValueError(f"export failed for {tool!r}: {exc}") from exc
    if output_path is not None:
        target = _resolve_output_path(output_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            raise ValueError(f"could not write {str(target)!r}: {exc}") from exc
        return {"tool": tool, "path": str(target), "bytes_written": len(data)}
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
    if domain not in DOMAIN_VOCAB:
        raise ValueError(f"unknown domain: {domain!r}; valid domains: {sorted(DOMAIN_VOCAB)}")
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
