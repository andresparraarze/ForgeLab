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
        server = create_server(AuthSettings.from_env(os.environ))
    return server, args


def main(argv: list[str] | None = None) -> None:
    server, args = _build(argv)
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    # Transport settings belong to run(), not to the constructor. Passing them
    # to a transport that ignores them would hide a typo, so stdio is dispatched
    # separately rather than handing it a host and port it will drop.
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
