import json

import pytest

from forgelab import cli


def _run(capsys, *argv):
    cli.main(list(argv))
    return capsys.readouterr().out


def test_init_hermes_prints_config_and_creates_dir(tmp_path, capsys):
    out_dir = tmp_path / "designs"
    out = _run(capsys, "init", "--agent", "hermes", "--output-dir", str(out_dir))
    assert out_dir.is_dir()
    assert "forgelab-mcp" in out
    assert str(out_dir) in out
    config = json.loads(out[out.index("{") : out.rindex("}") + 1])
    server = config["mcpServers"]["forgelab"]
    assert server["args"] == ["--transport", "stdio"]
    assert server["env"]["FORGELAB_OUTPUT_DIR"] == str(out_dir)


@pytest.mark.parametrize("agent", ["openclaw", "other"])
def test_init_other_agents_print_config(tmp_path, capsys, agent):
    out = _run(capsys, "init", "--agent", agent, "--output-dir", str(tmp_path / "o"))
    assert "mcpServers" in out
    assert "forgelab-mcp" in out


def test_init_claude_code_without_cli_prints_command(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    out = _run(capsys, "init", "--agent", "claude-code", "--output-dir", str(tmp_path / "o"))
    assert "claude mcp add forgelab" in out
    assert "--transport stdio" in out


def test_init_claude_code_with_cli_runs_command(tmp_path, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, check: calls.append(cmd))
    out = _run(capsys, "init", "--agent", "claude-code", "--output-dir", str(tmp_path / "o"))
    assert len(calls) == 1
    assert calls[0][:4] == ["claude", "mcp", "add", "forgelab"]
    assert "registered" in out.lower()


def test_init_interactive_prompts(tmp_path, capsys, monkeypatch):
    answers = iter(["2", str(tmp_path / "picked")])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = _run(capsys, "init")
    assert (tmp_path / "picked").is_dir()
    assert "mcpServers" in out  # hermes (option 2) prints a config block
