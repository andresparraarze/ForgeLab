import asyncio

from forgelab.auth.config import AuthSettings
from forgelab.mcp.server import create_server

_EXPECTED = {
    "validate_document",
    "get_domain_schema",
    "get_prompt",
    "list_domains",
    "list_formats",
    "load_document",
    "diff_documents",
    "verify_sync",
    "generate_bom",
    "list_components",
    "get_component",
    "create_project",
    "load_project",
    "update_project",
    "export_project",
    "get_history",
    "get_project_summary",
    "check_fabrication",
    "list_fab_profiles",
    "auto_place",
    "get_projection_schema",
    "calculate_pad_positions",
    "calculate_polygon",
    "calculate_rotation_matrix",
    "calculate_trace_width",
    "calculate_board_layout",
    "patch_document",
    "export_document",
    "import_file",
    "generate_document",
    "analyze_image",
    "generation_status",
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
