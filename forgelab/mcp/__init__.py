"""ForgeLab MCP server — exposes ForgeLab as MCP tools over stdio and HTTP.

Frontend peer to ``forgelab.api``: depends on core/spec/sdk/auth and reaches
importers/exporters only through the registry. The ``mcp`` SDK is confined to
this package.
"""

from forgelab.mcp.server import create_server

__all__ = ["create_server"]
