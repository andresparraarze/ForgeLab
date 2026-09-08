"""What `forgelab init` and `forgelab update` actually run.

These tests exist because the four agent CLIs ForgeLab registers with disagree
in small, undocumented ways, and every one of those differences has already
been got wrong at least once:

* ``claude mcp add`` defaults to ``--scope local``, which files the server
  under the *current directory's* project entry — install from ``$HOME`` and
  ForgeLab is invisible everywhere else.
* ``hermes mcp add`` passes server arguments through ``--args`` (nargs="*"),
  which argparse cannot fill with a value starting in ``-``.
* OpenClaw spells removal ``unset``; it has no ``mcp remove``.
* Hermes and OpenClaw probe the server and then *ask* before saving, which
  under ``curl ... | bash`` would eat the rest of the install script.

So the assertions are on exact argv, not on "a command was run". Each agent's
CLI is a stub on PATH that records what it was called with.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
from pathlib import Path

import pytest

from forgelab import cli

_LOG = "argv.log"


@pytest.fixture
def stub_cli(tmp_path, monkeypatch):
    """Put fake agent CLIs on PATH; return a reader for what they received."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / _LOG

    def install(*names: str) -> None:
        for name in names:
            exe = bindir / name
            exe.write_text(
                "#!/bin/sh\n"
                f'printf "%s\\n" "{name} $*" >> "{log}"\n'
                # Drain stdin so a test can prove the caller supplied it rather
                # than leaving the child to inherit the parent's.
                f'stdin=$(cat); printf "stdin:%s:%s\\n" "{name}" "$stdin" >> "{log}"\n'
            )
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

    def lines() -> list[str]:
        return log.read_text().splitlines() if log.exists() else []

    install.lines = lines  # type: ignore[attr-defined]
    return install


def _run(capsys, *argv):
    cli.main(list(argv))
    return capsys.readouterr().out


def _commands(stub_cli) -> list[str]:
    return [ln for ln in stub_cli.lines() if not ln.startswith("stdin:")]


# --- registration -----------------------------------------------------------


def test_claude_code_registers_at_user_scope(tmp_path, capsys, stub_cli):
    """The regression that made ForgeLab invisible outside the install dir."""
    stub_cli("claude")
    out = _run(capsys, "init", "--agent", "claude-code", "--output-dir", str(tmp_path / "o"))

    add = [c for c in _commands(stub_cli) if " mcp add " in c]
    assert len(add) == 1
    assert "--scope user" in add[0]
    assert "--transport stdio" in add[0]
    assert f"--env FORGELAB_OUTPUT_DIR={tmp_path / 'o'}" in add[0]
    assert "registered" in out.lower()


def test_claude_code_clears_a_previous_local_scope_entry(tmp_path, capsys, stub_cli):
    """An install predating --scope user left a local entry that would shadow."""
    stub_cli("claude")
    _run(capsys, "init", "--agent", "claude-code", "--output-dir", str(tmp_path / "o"))

    removes = [c for c in _commands(stub_cli) if " mcp remove " in c]
    assert removes == [
        "claude mcp remove forgelab -s local",
        "claude mcp remove forgelab -s user",
    ]


def test_codex_registers_over_stdio(tmp_path, capsys, stub_cli):
    stub_cli("codex")
    _run(capsys, "init", "--agent", "codex", "--output-dir", str(tmp_path / "o"))

    add = [c for c in _commands(stub_cli) if " mcp add " in c]
    assert add == [
        f"codex mcp add forgelab --env FORGELAB_OUTPUT_DIR={tmp_path / 'o'} "
        f"-- {cli._server_command()} --transport stdio"
    ]


def test_hermes_passes_no_server_arguments(tmp_path, capsys, stub_cli):
    """--args cannot carry a value beginning with '-', so nothing is passed.

    This is only correct because forgelab-mcp defaults to stdio; the default is
    pinned by test_mcp_cli.test_stdio_is_the_default_transport.
    """
    stub_cli("hermes")
    _run(capsys, "init", "--agent", "hermes", "--output-dir", str(tmp_path / "o"))

    add = [c for c in _commands(stub_cli) if " mcp add " in c]
    assert add == [
        f"hermes mcp add forgelab --command {cli._server_command()} "
        f"--env FORGELAB_OUTPUT_DIR={tmp_path / 'o'}"
    ]
    assert "--transport" not in add[0]


def test_openclaw_removal_is_spelled_unset(tmp_path, capsys, stub_cli):
    """OpenClaw has no `mcp remove`; calling it would silently do nothing."""
    stub_cli("openclaw")
    _run(capsys, "init", "--agent", "openclaw", "--output-dir", str(tmp_path / "o"))

    assert "openclaw mcp unset forgelab" in _commands(stub_cli)
    assert not any(" mcp remove " in c for c in _commands(stub_cli))


def test_openclaw_passes_transport_as_repeated_arg_flags(tmp_path, capsys, stub_cli):
    stub_cli("openclaw")
    _run(capsys, "init", "--agent", "openclaw", "--output-dir", str(tmp_path / "o"))

    add = [c for c in _commands(stub_cli) if " mcp add " in c]
    assert add == [
        f"openclaw mcp add forgelab --command {cli._server_command()} "
        f"--arg --transport --arg stdio --env FORGELAB_OUTPUT_DIR={tmp_path / 'o'}"
    ]


@pytest.mark.parametrize("agent", ["hermes", "openclaw"])
def test_prompting_clis_are_answered_not_left_to_inherit_stdin(tmp_path, capsys, stub_cli, agent):
    """Under `curl | bash` the parent's stdin is the install script itself."""
    stub_cli(cli._REGISTRARS[agent].binary)
    _run(capsys, "init", "--agent", agent, "--output-dir", str(tmp_path / "o"))

    answered = [ln for ln in stub_cli.lines() if ln.startswith("stdin:")]
    assert answered, "the registrar was given no stdin at all"
    assert all(ln.endswith(":y") for ln in answered), answered


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_non_prompting_clis_still_get_a_closed_stdin(tmp_path, capsys, stub_cli, agent):
    stub_cli(cli._REGISTRARS[agent].binary)
    _run(capsys, "init", "--agent", agent, "--output-dir", str(tmp_path / "o"))

    assert all(ln.endswith(":") for ln in stub_cli.lines() if ln.startswith("stdin:"))


@pytest.mark.parametrize("agent", sorted(cli._REGISTRARS))
def test_every_registrar_creates_the_output_dir(tmp_path, capsys, stub_cli, agent):
    stub_cli(cli._REGISTRARS[agent].binary)
    out_dir = tmp_path / "designs"
    _run(capsys, "init", "--agent", agent, "--output-dir", str(out_dir))
    assert out_dir.is_dir()


@pytest.mark.parametrize("agent", sorted(cli._REGISTRARS))
def test_missing_cli_prints_a_runnable_command_and_fails(tmp_path, capsys, monkeypatch, agent):
    """Exit non-zero: install-*.sh runs under `set -e` and must not say Done."""
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["init", "--agent", agent, "--output-dir", str(tmp_path / "o")])
    assert excinfo.value.code == 1

    out = capsys.readouterr().out
    binary = cli._REGISTRARS[agent].binary
    printed = [ln for ln in out.splitlines() if ln.strip().startswith(binary)]
    assert printed, out
    # Whatever is printed must be a real command, not prose.
    assert shlex.split(printed[0])[:3] == [binary, "mcp", "add"]


def test_unknown_agent_falls_back_to_a_config_block(tmp_path, capsys):
    out = _run(capsys, "init", "--agent", "other", "--output-dir", str(tmp_path / "o"))
    config = json.loads(out[out.index("{") : out.rindex("}") + 1])
    server = config["mcpServers"]["forgelab"]
    assert server["args"] == ["--transport", "stdio"]
    assert server["env"]["FORGELAB_OUTPUT_DIR"] == str(tmp_path / "o")


def test_interactive_prompts_pick_by_number(tmp_path, capsys, monkeypatch):
    answers = iter([str(len(cli._AGENTS)), str(tmp_path / "picked")])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = _run(capsys, "init")
    assert (tmp_path / "picked").is_dir()
    assert "mcpServers" in out  # the last option is 'other'


def test_interactive_zero_is_not_read_as_the_last_agent(tmp_path, capsys, monkeypatch):
    """`_AGENTS[0 - 1]` is the last entry, not an error."""
    answers = iter(["0", str(tmp_path / "picked")])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = _run(capsys, "init")
    assert "Unrecognized choice" in out


# --- update -----------------------------------------------------------------


@pytest.fixture
def fake_venv(tmp_path, monkeypatch):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "pip").touch()
    (venv / "bin" / "python").touch()
    monkeypatch.setattr(cli, "_FORGELAB_VENV", venv)
    return venv


def _stub_update(monkeypatch, versions):
    """Record pip's argv; report `versions` from successive version probes."""
    calls: list[list[str]] = []
    seen = iter(versions)

    class Result:
        def __init__(self, stdout):
            self.stdout = stdout
            self.returncode = 0

    def fake_run(cmd, check=False, capture_output=False, text=False, input=None):
        calls.append(cmd)
        return Result(next(seen) + "\n" if capture_output else "")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    return calls


def test_update_reports_the_version_it_moved_between(fake_venv, capsys, monkeypatch):
    """SPEC_VERSION used to be printed here, and it never changes."""
    _stub_update(monkeypatch, ["0.1.1.dev288+gaaaaaaa", "0.1.1.dev289+gbbbbbbb"])
    out = _run(capsys, "update")

    assert "0.1.1.dev288+gaaaaaaa → 0.1.1.dev289+gbbbbbbb" in out
    assert "updated" in out.lower()


def test_update_says_so_when_nothing_moved(fake_venv, capsys, monkeypatch):
    _stub_update(monkeypatch, ["0.1.1.dev289+gbbbbbbb", "0.1.1.dev289+gbbbbbbb"])
    out = _run(capsys, "update")
    assert "already up to date" in out.lower()


def test_update_does_not_force_reinstall_the_dependency_tree(fake_venv, capsys, monkeypatch):
    """--force-reinstall is global in pip: it rebuilt all ~30 transitive deps.

    The version is derived from git now, so pip reinstalls forgelab on its own
    whenever the commit moved and a plain --upgrade is enough.
    """
    calls = _stub_update(monkeypatch, ["a", "b"])
    _run(capsys, "update")

    pip_call = next(c for c in calls if "install" in c)
    assert "--force-reinstall" not in pip_call
    assert "--no-cache-dir" not in pip_call
    assert "--upgrade" in pip_call


def test_update_installs_the_extras_the_tools_need(fake_venv, capsys, monkeypatch):
    """preview_render is an MCP tool; without [preview] it is a broken one."""
    calls = _stub_update(monkeypatch, ["a", "b"])
    _run(capsys, "update")

    requirement = next(c for c in calls if "install" in c)[-1]
    assert requirement.startswith("forgelab[mcp,agent,preview] @ git+")


def test_update_without_install_prints_guidance(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_FORGELAB_VENV", tmp_path / "missing")
    called = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: called.append(a))
    with pytest.raises(SystemExit):
        cli.main(["update"])
    out = capsys.readouterr().out
    assert "install" in out.lower()
    assert not called


# --- version ----------------------------------------------------------------


def test_version_reports_both_the_build_and_the_spec(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0

    out = capsys.readouterr().out
    from forgelab import SPEC_VERSION, __version__

    assert __version__ in out
    assert SPEC_VERSION in out


def test_version_is_derived_not_a_frozen_literal():
    """A static version made `update` unable to report that anything changed."""
    from forgelab import __version__

    assert __version__ != "0.1.0", "version looks hardcoded again"
    assert Path("forgelab/__init__.py").read_text().count('"0.1.0"') == 0
