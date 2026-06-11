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


def test_update_runs_pip_upgrade_and_prints_version(tmp_path, capsys, monkeypatch):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "pip").touch()
    (venv / "bin" / "python").touch()
    monkeypatch.setattr(cli, "_FORGELAB_VENV", venv)
    calls = []

    def fake_run(cmd, check, capture_output=False, text=False):
        calls.append(cmd)

        class R:
            stdout = "0.5.0\n"

        return R()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    out = _run(capsys, "update")
    assert calls[0][:3] == [str(venv / "bin" / "pip"), "install", "--upgrade"]
    assert "git+https://github.com/andresparraarze/ForgeLab" in calls[0][3]
    assert str(venv / "bin" / "python") in calls[1]
    assert "0.5.0" in out
    assert "updated" in out.lower()


def test_update_without_install_prints_guidance(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_FORGELAB_VENV", tmp_path / "missing")
    called = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: called.append(a))
    with pytest.raises(SystemExit):
        cli.main(["update"])
    out = capsys.readouterr().out
    assert "install" in out.lower()
    assert not called
