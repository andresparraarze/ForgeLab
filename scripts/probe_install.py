"""Ask an installed ForgeLab MCP server whether it actually works.

Run by scripts/verify-install.sh against the venv the installer just created,
not against the development checkout — the point is to exercise what a user
ends up with, over a real stdio connection.

The server is started with *no arguments*, which is exactly how
`forgelab init --agent hermes` registers it: `hermes mcp add` passes server
arguments through --args (nargs="*"), which argparse cannot fill with a value
beginning in "-". If forgelab-mcp ever stops defaulting to stdio, this hangs
here rather than in a user's session.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = 40


async def probe(venv: str, repo: str, output_dir: str) -> None:
    params = StdioServerParameters(
        command=os.path.join(venv, "bin", "forgelab-mcp"),
        args=[],
        env={**os.environ, "FORGELAB_OUTPUT_DIR": output_dir},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = (await session.list_tools()).tools
            if len(tools) != EXPECTED_TOOLS:
                raise SystemExit(f"expected {EXPECTED_TOOLS} tools, got {len(tools)}")

            result = await session.call_tool("list_domains", {})
            if result.is_error:
                raise SystemExit(f"list_domains failed: {result.content}")

            # preview_render needs the 'preview' extra. It shipped broken on
            # every clean install until install.sh started asking for it, and
            # nothing in the test suite noticed because dev machines carry
            # matplotlib for other reasons.
            png = os.path.join(output_dir, "verify-preview.png")
            result = await session.call_tool(
                "preview_render",
                {
                    "document_path": os.path.join(repo, "examples/threed/cube.forge.json"),
                    "output_path": png,
                },
            )
            if result.is_error:
                text = result.content[0].text if result.content else "<no content>"
                raise SystemExit(f"preview_render failed: {text}")
            if not os.path.exists(png) or os.path.getsize(png) == 0:
                raise SystemExit("preview_render reported success but wrote no PNG")

    print(f"  {len(tools)} tools, list_domains ok, preview PNG {os.path.getsize(png)} bytes")


if __name__ == "__main__":
    asyncio.run(probe(*sys.argv[1:4]))
