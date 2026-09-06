import asyncio
import shutil
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from forgelab.auth.config import AuthSettings
from forgelab.mcp.server import _TOOLS, _guard, create_server

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
    "check_gerber_completeness",
    "list_fab_profiles",
    "auto_place",
    "route_board",
    "preview_render",
    "critique_render",
    "verify_geometry",
    "get_projection_schema",
    "calculate_pad_positions",
    "calculate_polygon",
    "calculate_bolt_circle",
    "calculate_rounded_rect",
    "calculate_slot",
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


# --- the error boundary ----------------------------------------------------- #
#
# The SDK separates a failure a tool meant to report from a crash: ToolError
# keeps its message, and everything else reaches the client as the bare string
# "Error executing tool <name>" with the real text logged server-side. ForgeLab
# raises ValueError for everything actionable and ToolError nowhere, so without
# the translation in server._guard every message the tools are built around
# would arrive as nothing at all. These tests are what hold that translation in
# place.


def _run_tool(server, name, **arguments):
    """Invoke a registered tool the way the SDK does, returning the exception."""
    tool = server._tool_manager.get_tool(name)
    try:
        asyncio.run(tool.run(arguments, context=None))
    except Exception as exc:  # noqa: BLE001 - the exception is the assertion
        return exc
    return None


def _boundary_server(fn, name):
    server = create_server(None)
    server.add_tool(_guard(fn), name=name)
    return server


def test_an_actionable_message_reaches_the_caller():
    def failing() -> str:
        raise ValueError("FreeCAD is not installed: 'freecadcmd' is not on PATH")

    exc = _run_tool(_boundary_server(failing, "failing"), "failing")
    assert isinstance(exc, ToolError)
    assert "freecadcmd" in str(exc)


def test_a_missing_scope_reaches_the_caller():
    """require_scope raises PermissionError, and the caller must be told which.

    Reported, not hidden: a token lacking a scope is a fact about the request,
    not a bug in the server.
    """

    def denied() -> str:
        raise PermissionError("missing required scope: forge:export")

    exc = _run_tool(_boundary_server(denied, "denied"), "denied")
    assert isinstance(exc, ToolError)
    assert "forge:export" in str(exc)


def test_a_crash_does_not_masquerade_as_user_error():
    """The other half, and the reason this is not a blanket `except Exception`.

    A genuine bug must stay a crash: logged with its traceback, and reported to
    the model only as a failure. Turning every exception into a ToolError would
    hand the model an AttributeError to try to work around, and would quietly
    put internals on the wire.
    """

    def crashing() -> str:
        raise TypeError("secret internal detail")

    exc = _run_tool(_boundary_server(crashing, "crashing"), "crashing")
    assert isinstance(exc, UnexpectedToolError)
    assert "secret internal detail" not in str(exc)


def test_wrapping_preserves_every_tool_schema():
    """add_tool reads the function it is handed, so the wrapper must be see-through.

    Without functools.wraps every one of the 40 tools would advertise
    (*args, **kwargs) — the server would still start, list its tools, and be
    unusable.
    """
    wrapped = {t.name: t for t in asyncio.run(create_server(None).list_tools())}
    bare = MCPServer("bare")
    for fn in _TOOLS:
        bare.add_tool(fn)
    for tool in asyncio.run(bare.list_tools()):
        mirror = wrapped[tool.name]
        assert mirror.input_schema == tool.input_schema, tool.name
        assert mirror.output_schema == tool.output_schema, tool.name
        assert mirror.description == tool.description, tool.name


def test_a_real_tool_reports_a_missing_kernel_through_the_boundary(tmp_path, monkeypatch):
    """End to end on a real tool, since the unit tests above use fakes.

    This is the exact failure that broke CI: a mechanical document and no
    FreeCAD. The message has to survive registration, the guard, and the SDK's
    error handling to be of any use to the model.
    """
    real = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda n, *a, **k: None if n == "freecadcmd" else real(n, *a, **k)
    )
    example = Path(__file__).resolve().parents[1] / "examples/mechanical/motor_mount.forge.json"
    part = tmp_path / "part.forge.json"
    part.write_bytes(example.read_bytes())
    exc = _run_tool(create_server(None), "verify_geometry", document_path=str(part))
    assert isinstance(exc, ToolError)
    assert "freecadcmd" in str(exc)
