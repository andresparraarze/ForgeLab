"""The ``forgelab`` CLI: ``init``, ``update`` and ``--version``.

``init`` connects the ForgeLab MCP server to an agent. Every agent that ships a
CLI is registered by running it; the JSON config block is the fallback for
agents that have none.

This module is the single definition of how ForgeLab registers itself. The
``scripts/install-*.sh`` wrappers call ``forgelab init --agent <name>`` rather
than rebuilding the commands in shell, so there is one place a flag can be
wrong and one place a test has to cover.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_URL = "https://github.com/andresparraarze/ForgeLab"
_FORGELAB_VENV = Path.home() / ".forgelab" / "venv"


@dataclass(frozen=True)
class _Registrar:
    """How one agent's CLI is told about the ForgeLab MCP server.

    ``add``/``remove`` build argv rather than shell strings so the commands can
    be asserted exactly in tests — the differences between these four CLIs are
    small, undocumented in any one place, and easy to copy wrong.
    """

    agent: str
    binary: str
    label: str
    install_hint: str
    # Some CLIs probe the server and then ask before saving. In a curl | bash
    # install stdin is the script itself, so the answer must be supplied.
    confirms: bool = False

    def add(self, command: str, output_dir: str) -> list[str]:
        raise NotImplementedError

    def remove(self) -> list[list[str]]:
        raise NotImplementedError


@dataclass(frozen=True)
class _ClaudeCode(_Registrar):
    def add(self, command: str, output_dir: str) -> list[str]:
        # --scope user, not the default: `claude mcp add` defaults to `local`,
        # which files the server under the *current directory's* project entry
        # in ~/.claude.json. Installing from $HOME then leaves ForgeLab
        # invisible in every other directory the user works in.
        return [
            "claude", "mcp", "add", "forgelab", "--scope", "user",
            "--env", f"FORGELAB_OUTPUT_DIR={output_dir}",
            "--", command, "--transport", "stdio",
        ]  # fmt: skip

    def remove(self) -> list[list[str]]:
        # Both scopes: a machine installed before --scope user was passed still
        # carries a local-scope entry, and the two would otherwise coexist.
        return [
            ["claude", "mcp", "remove", "forgelab", "-s", "local"],
            ["claude", "mcp", "remove", "forgelab", "-s", "user"],
        ]


@dataclass(frozen=True)
class _Codex(_Registrar):
    def add(self, command: str, output_dir: str) -> list[str]:
        return [
            "codex", "mcp", "add", "forgelab",
            "--env", f"FORGELAB_OUTPUT_DIR={output_dir}",
            "--", command, "--transport", "stdio",
        ]  # fmt: skip

    def remove(self) -> list[list[str]]:
        return [["codex", "mcp", "remove", "forgelab"]]


@dataclass(frozen=True)
class _Hermes(_Registrar):
    def add(self, command: str, output_dir: str) -> list[str]:
        # No transport argument. `hermes mcp add` takes server arguments via
        # --args (nargs="*"), which argparse cannot fill with a value starting
        # in "-": `--args --transport stdio` fails with "unrecognized
        # arguments", and `--args=--transport --args=stdio` keeps only the last.
        # forgelab-mcp defaults to stdio, so the right move is to pass nothing —
        # test_stdio_is_the_default_transport pins the default this depends on.
        return [
            "hermes", "mcp", "add", "forgelab",
            "--command", command,
            "--env", f"FORGELAB_OUTPUT_DIR={output_dir}",
        ]  # fmt: skip

    def remove(self) -> list[list[str]]:
        return [["hermes", "mcp", "remove", "forgelab"]]


@dataclass(frozen=True)
class _OpenClaw(_Registrar):
    def add(self, command: str, output_dir: str) -> list[str]:
        return [
            "openclaw", "mcp", "add", "forgelab",
            "--command", command,
            "--arg", "--transport", "--arg", "stdio",
            "--env", f"FORGELAB_OUTPUT_DIR={output_dir}",
        ]  # fmt: skip

    def remove(self) -> list[list[str]]:
        # "unset", not "remove" — OpenClaw has no `mcp remove` subcommand.
        return [["openclaw", "mcp", "unset", "forgelab"]]


_REGISTRARS: dict[str, _Registrar] = {
    "claude-code": _ClaudeCode(
        agent="claude-code",
        binary="claude",
        label="Claude Code",
        install_hint="https://claude.com/claude-code",
    ),
    "codex": _Codex(
        agent="codex",
        binary="codex",
        label="Codex CLI",
        install_hint="https://developers.openai.com/codex/cli",
    ),
    "hermes": _Hermes(
        agent="hermes",
        binary="hermes",
        label="Hermes Agent",
        install_hint="https://github.com/NousResearch/hermes-agent",
        confirms=True,
    ),
    "openclaw": _OpenClaw(
        agent="openclaw",
        binary="openclaw",
        label="OpenClaw",
        install_hint="https://docs.openclaw.ai",
        confirms=True,
    ),
}

_AGENTS = [*_REGISTRARS, "other"]

_CONFIG_HINT = "Add this to your agent's MCP config (most agents use this shape):"


def _server_command() -> str:
    """Absolute path to forgelab-mcp in the running environment, if it exists."""
    candidate = Path(sys.executable).parent / "forgelab-mcp"
    return str(candidate) if candidate.exists() else "forgelab-mcp"


def _ask_agent() -> str:
    print("Which agent do you use?")
    for i, name in enumerate(_AGENTS, 1):
        print(f"  {i}. {name}")
    choice = input(f"Choose [1-{len(_AGENTS)}] (default 1): ").strip() or "1"
    try:
        index = int(choice)
        if index < 1:
            raise IndexError(choice)
        return _AGENTS[index - 1]
    except (ValueError, IndexError):
        print(f"Unrecognized choice {choice!r}; using 'other'.")
        return "other"


def _ask_output_dir() -> str:
    default = str(Path.home() / "forgelab-output")
    answer = input(f"Where should exported files be saved? [{default}]: ").strip()
    return answer or default


def _config_block(command: str, output_dir: str) -> str:
    return json.dumps(
        {
            "mcpServers": {
                "forgelab": {
                    "command": command,
                    "args": ["--transport", "stdio"],
                    "env": {"FORGELAB_OUTPUT_DIR": output_dir},
                }
            }
        },
        indent=2,
    )


def _register(reg: _Registrar, command: str, output_dir: str) -> bool:
    """Run the agent's CLI. Returns False when the CLI is not installed."""
    if not shutil.which(reg.binary):
        print(f"The {reg.binary!r} CLI was not found on PATH.")
        print(f"Install {reg.label} ({reg.install_hint}), then run:")
        print(f"  {shlex.join(reg.add(command, output_dir))}")
        print(f"Or re-run: forgelab init --agent {reg.agent}")
        return False

    # "y" answers the tool-enable / save prompt some CLIs raise after probing
    # the server. stdin is always supplied, never inherited: under
    # `curl ... | bash` the parent's stdin is the install script itself, so a
    # prompting CLI would silently eat the rest of it.
    answer = "y\n" if reg.confirms else ""
    for argv in reg.remove():
        subprocess.run(argv, capture_output=True, check=False, input=answer, text=True)
    subprocess.run(reg.add(command, output_dir), check=True, input=answer, text=True)
    print(f"✔ Registered with {reg.label} as MCP server 'forgelab'.")
    return True


def _init(agent: str, output_dir: str) -> None:
    out = Path(output_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    command = _server_command()

    print(f"✔ Output directory ready: {out}")

    reg = _REGISTRARS.get(agent)
    if reg is not None:
        if not _register(reg, command, str(out)):
            # Non-zero: the caller asked for this agent and it was not
            # connected. The install-*.sh wrappers run under `set -e`, so a
            # silent success here would end with "Done!" over a no-op.
            raise SystemExit(1)
        print(f"Next step: restart {reg.label} and ask it to")
        print('  "generate a blinky LED board and export it to KiCad".')
        return

    print(_CONFIG_HINT)
    print(_config_block(command, str(out)))
    print("Next step: restart the agent and ask it to call the ForgeLab tool")
    print("'list_domains' to confirm the connection (expected: hardware,")
    print("mechanical, threed).")


def _installed_version(python: Path) -> str:
    """The version of forgelab in another venv, or '' if it cannot be read."""
    result = subprocess.run(
        [str(python), "-c", "import forgelab; print(forgelab.__version__)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _update() -> None:
    """Upgrade the ~/.forgelab/venv install from the GitHub repo."""
    pip = _FORGELAB_VENV / "bin" / "pip"
    python = _FORGELAB_VENV / "bin" / "python"
    if not pip.exists():
        print(f"No ForgeLab install found at {_FORGELAB_VENV}.")
        print("Run the installer first:")
        print(f"  curl -fsSL {_REPO_URL}/raw/main/scripts/install-claude-code.sh | bash")
        raise SystemExit(1)

    before = _installed_version(python)
    print(f"→ Upgrading ForgeLab from GitHub (currently {before or 'unknown'})…")
    # A plain --upgrade is enough. The version is derived from git, so every
    # commit is a distinct version and pip reinstalls on its own; the old
    # --force-reinstall --no-cache-dir rebuilt all ~30 transitive dependencies
    # on every run to work around a static 0.1.0 that no longer exists.
    subprocess.run(
        [
            str(pip),
            "install",
            "--upgrade",
            f"forgelab[mcp,agent,preview] @ git+{_REPO_URL}",
        ],
        check=True,
    )
    after = _installed_version(python)
    if after and after == before:
        print(f"✔ Already up to date — {after}.")
    else:
        print(f"✔ ForgeLab updated — {before or 'unknown'} → {after or 'unknown'}.")


def _version() -> str:
    from forgelab import SPEC_VERSION, __version__

    return f"forgelab {__version__} (document spec {SPEC_VERSION})"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="forgelab", description="ForgeLab CLI")
    parser.add_argument("--version", action="version", version=_version())
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="connect ForgeLab to your AI agent")
    init.add_argument("--agent", choices=_AGENTS, help="skip the interactive question")
    init.add_argument("--output-dir", help="skip the interactive question")
    sub.add_parser("update", help="upgrade the ~/.forgelab install from GitHub")
    args = parser.parse_args(argv)

    if args.command == "init":
        agent = args.agent or _ask_agent()
        output_dir = args.output_dir or _ask_output_dir()
        _init(agent, output_dir)
    elif args.command == "update":
        _update()


if __name__ == "__main__":
    main()
