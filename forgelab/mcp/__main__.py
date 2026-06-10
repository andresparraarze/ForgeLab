"""CLI: run the ForgeLab MCP server over stdio or Streamable HTTP."""

from __future__ import annotations

import argparse
import os

from forgelab.auth import AuthSettings
from forgelab.mcp.server import create_server


def _build(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(prog="forgelab-mcp", description="ForgeLab MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)
    if args.transport == "stdio":
        server = create_server(None)
    else:
        server = create_server(AuthSettings.from_env(os.environ), host=args.host, port=args.port)
    return server, args


def main(argv: list[str] | None = None) -> None:
    server, args = _build(argv)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
