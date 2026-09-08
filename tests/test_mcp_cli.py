"""The forgelab-mcp entry point: what the CLI flags actually reach.

These tests carry a scar. The unauthenticated server branch once dropped host
and port on the floor, so `--port 8001` was accepted and the server then bound
8000. Transport settings now live on `run()` rather than on the constructor, so
the assertions moved with them — but they still assert the same thing, because
"the flag is parsed" was never the interesting half.
"""

import pytest

from forgelab.mcp import __main__ as cli


class FakeServer:
    """Records the run() call instead of binding a socket."""

    def __init__(self):
        self.run_kwargs = None
        self.transport = None

    def run(self, transport, **kwargs):
        self.transport = transport
        self.run_kwargs = kwargs


@pytest.fixture
def served(monkeypatch):
    """Run the CLI against a fake server and hand back what it received."""

    def run(argv):
        server = FakeServer()
        monkeypatch.setattr(cli, "create_server", lambda *a, **k: server)
        cli.main(argv)
        return server

    return run


def test_build_defaults_to_stdio():
    server, args = cli._build([])
    assert args.transport == "stdio"
    assert server.name == "forgelab"


def test_build_parses_host_and_port():
    _, args = cli._build(["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9000"])
    assert args.transport == "streamable-http"
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_main_dispatches_transport_to_run(served):
    assert served(["--transport", "stdio"]).transport == "stdio"


def test_http_transport_receives_host_and_port(served):
    """The assertion that matters: the flags must reach the running server.

    `--port` was once accepted and then ignored, and the server bound the SDK's
    default instead. Parsing the flag is not evidence of anything.
    """
    server = served(["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9000"])
    assert server.transport == "streamable-http"
    assert server.run_kwargs["host"] == "0.0.0.0"
    assert server.run_kwargs["port"] == 9000


def test_http_defaults_bind_port_8001(served):
    """8001, not the SDK's 8000 — the API server has 8000."""
    server = served(["--transport", "streamable-http"])
    assert server.run_kwargs["port"] == 8001
    assert server.run_kwargs["host"] == "127.0.0.1"


def test_http_transport_is_stateless_with_json_responses(served):
    """Both are required for the HTTP transport ForgeLab documents.

    They used to be constructor arguments, which meant they were set even for
    stdio, where they mean nothing. Losing them in the move to run() would be
    silent — the server would still start, and only behave differently.
    """
    kwargs = served(["--transport", "streamable-http"]).run_kwargs
    assert kwargs["stateless_http"] is True
    assert kwargs["json_response"] is True


def test_stdio_is_not_given_transport_settings(served):
    """stdio has no host or port; handing it some would hide a typo."""
    assert served(["--transport", "stdio"]).run_kwargs == {}


def test_stdio_is_the_default_transport():
    """`forgelab init --agent hermes` depends on this default.

    `hermes mcp add` passes server arguments through --args (nargs="*"), which
    argparse cannot fill with a value beginning in "-": `--args --transport
    stdio` fails outright. ForgeLab is therefore registered there as the bare
    command with no arguments, so changing this default would silently turn
    every Hermes install into an HTTP server nobody is listening to.
    """
    _, args = cli._build([])
    assert args.transport == "stdio"
