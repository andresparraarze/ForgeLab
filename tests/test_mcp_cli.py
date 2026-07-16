from forgelab.mcp import __main__ as cli


def test_build_defaults_to_stdio():
    server, args = cli._build([])
    assert args.transport == "stdio"
    assert server.name == "forgelab"


def test_build_http_parses_host_port():
    server, args = cli._build(
        ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9000"]
    )
    assert args.transport == "streamable-http"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    # The server must actually receive them: auth is off by default, and the
    # unauthenticated FastMCP branch used to drop host/port on the floor —
    # `--port 8001` was accepted, then the server bound FastMCP's default 8000.
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 9000


def test_build_http_defaults_bind_port_8001():
    server, args = cli._build(["--transport", "streamable-http"])
    assert args.port == 8001
    assert server.settings.port == 8001


def test_main_dispatches_transport_to_run(monkeypatch):
    recorded = {}

    class FakeServer:
        def run(self, transport):
            recorded["transport"] = transport

    monkeypatch.setattr(cli, "create_server", lambda *a, **k: FakeServer())
    cli.main(["--transport", "stdio"])
    assert recorded["transport"] == "stdio"
