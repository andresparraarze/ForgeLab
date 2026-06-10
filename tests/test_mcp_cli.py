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


def test_main_dispatches_transport_to_run(monkeypatch):
    recorded = {}

    class FakeServer:
        def run(self, transport):
            recorded["transport"] = transport

    monkeypatch.setattr(cli, "create_server", lambda *a, **k: FakeServer())
    cli.main(["--transport", "stdio"])
    assert recorded["transport"] == "stdio"
