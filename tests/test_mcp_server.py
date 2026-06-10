import asyncio

from forgelab.auth.config import AuthSettings
from forgelab.mcp.server import create_server

_EXPECTED = {
    "validate_document",
    "get_domain_schema",
    "get_prompt",
    "list_domains",
    "list_formats",
    "export_document",
    "import_file",
    "generate_document",
}


def _tool_names(server):
    return {t.name for t in asyncio.run(server.list_tools())}


def test_stdio_server_registers_all_tools():
    server = create_server(None)
    assert _tool_names(server) == _EXPECTED


def test_http_server_builds_with_auth_and_all_tools():
    settings = AuthSettings(enabled=True, mode="dev", dev_secret="a" * 32)
    server = create_server(settings)
    assert _tool_names(server) == _EXPECTED
    assert server.name == "forgelab"
