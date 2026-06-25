"""Assemble the ForgeLab MCP server (FastMCP) for stdio or Streamable HTTP."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

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
    tools.list_fab_profiles,
    tools.get_projection_schema,
    tools.calculate_pad_positions,
    tools.calculate_polygon,
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


def _register(mcp: FastMCP) -> None:
    for fn in _TOOLS:
        mcp.add_tool(fn)


def create_server(
    auth_settings: AuthSettings | None = None, *, host: str = "127.0.0.1", port: int = 8001
) -> FastMCP:
    """Build the MCP server.

    With an enabled ``auth_settings`` the Streamable HTTP transport is configured
    as an OAuth resource server (token verifier + protected-resource metadata).
    Otherwise an unauthenticated server (for stdio) is returned. ``host``/``port``
    apply only to the HTTP transport.
    """
    if auth_settings is not None and auth_settings.enabled:
        from mcp.server.auth.settings import AuthSettings as McpAuthSettings
        from pydantic import AnyHttpUrl

        issuer = os.environ.get("FORGELAB_MCP_ISSUER_URL", "http://localhost:8000")
        resource = os.environ.get("FORGELAB_MCP_RESOURCE_URL", "http://localhost:8001")
        mcp = FastMCP(
            "forgelab",
            host=host,
            port=port,
            stateless_http=True,
            json_response=True,
            token_verifier=ForgeLabTokenVerifier(auth_settings),
            auth=McpAuthSettings(
                issuer_url=AnyHttpUrl(issuer),
                resource_server_url=AnyHttpUrl(resource),
                required_scopes=[],
            ),
        )
    else:
        mcp = FastMCP("forgelab")
    _register(mcp)
    return mcp
