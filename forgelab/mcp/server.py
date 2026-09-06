"""Assemble the ForgeLab MCP server for stdio or Streamable HTTP."""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from forgelab.auth import AuthSettings
from forgelab.mcp import tools
from forgelab.mcp.auth_bridge import ForgeLabTokenVerifier

_TOOLS = [
    tools.validate_document,
    tools.get_domain_schema,
    tools.get_prompt,
    tools.list_domains,
    tools.list_formats,
    tools.load_document,
    tools.diff_documents,
    tools.verify_sync,
    tools.generate_bom,
    tools.list_components,
    tools.get_component,
    tools.create_project,
    tools.load_project,
    tools.update_project,
    tools.export_project,
    tools.get_history,
    tools.get_project_summary,
    tools.check_fabrication,
    tools.check_gerber_completeness,
    tools.list_fab_profiles,
    tools.auto_place,
    tools.route_board,
    tools.preview_render,
    tools.critique_render,
    tools.verify_geometry,
    tools.get_projection_schema,
    tools.calculate_pad_positions,
    tools.calculate_polygon,
    tools.calculate_bolt_circle,
    tools.calculate_rounded_rect,
    tools.calculate_slot,
    tools.calculate_rotation_matrix,
    tools.calculate_trace_width,
    tools.calculate_board_layout,
    tools.patch_document,
    tools.export_document,
    tools.import_file,
    tools.generate_document,
    tools.analyze_image,
    tools.generation_status,
]


def _guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Let a tool's own error text reach the model, and only its own.

    The SDK draws a line between a failure a tool *meant* to report and a crash.
    ``ToolError`` keeps its message; anything else reaches the client as the bare
    string ``Error executing tool <name>`` with the real text logged server-side,
    so a crash cannot leak internals to the model. Both halves of that are right,
    but ForgeLab does not raise ``ToolError`` anywhere — it raises ``ValueError``,
    by a convention every module follows — and so every actionable message the
    tools are built around ("FreeCAD is not installed…", "invalid document: …",
    "export not implemented for …") would arrive as nothing at all.

    Translating at the boundary keeps the distinction rather than erasing it:

    * ``ValueError`` — the project's "the caller can act on this" — becomes a
      ``ToolError`` and is shown. Every error class in ``forgelab`` that a caller
      is meant to read derives from it.
    * ``PermissionError`` from ``require_scope`` likewise: a token missing a
      scope is something the caller has to be told, not a crash.
    * Anything else falls through untouched, and the SDK does the right thing —
      logs it with a traceback and tells the model only that the tool failed. A
      genuine bug must not be able to dress itself up as user error.

    ``functools.wraps`` matters here: ``add_tool`` derives each tool's name,
    description and JSON schema from the function it is handed, and without it
    every tool would advertise ``(*args, **kwargs)``.
    """

    @functools.wraps(fn)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ValueError, PermissionError) as exc:
            raise ToolError(str(exc)) from exc

    return guarded


def _register(mcp: MCPServer) -> None:
    for fn in _TOOLS:
        mcp.add_tool(_guard(fn))


def create_server(auth_settings: AuthSettings | None = None) -> MCPServer:
    """Build the MCP server.

    With an enabled ``auth_settings`` the Streamable HTTP transport is configured
    as an OAuth resource server (token verifier + protected-resource metadata).
    Otherwise an unauthenticated server (for stdio) is returned.

    Transport settings — host, port, ``stateless_http``, ``json_response`` — are
    not arguments here: the SDK takes them at ``run()`` rather than on the
    constructor, so ``__main__`` passes them there. That split is worth knowing
    about, because the constructor used to accept a port and quietly ignore it.
    """
    if auth_settings is not None and auth_settings.enabled:
        from mcp.server.auth.settings import AuthSettings as McpAuthSettings
        from pydantic import AnyHttpUrl

        issuer = os.environ.get("FORGELAB_MCP_ISSUER_URL", "http://localhost:8000")
        resource = os.environ.get("FORGELAB_MCP_RESOURCE_URL", "http://localhost:8001")
        mcp = MCPServer(
            "forgelab",
            token_verifier=ForgeLabTokenVerifier(auth_settings),
            auth=McpAuthSettings(
                issuer_url=AnyHttpUrl(issuer),
                resource_server_url=AnyHttpUrl(resource),
                required_scopes=[],
            ),
        )
    else:
        mcp = MCPServer("forgelab")
    _register(mcp)
    return mcp
