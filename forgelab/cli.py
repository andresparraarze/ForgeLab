"""The ``forgelab`` CLI. Currently one subcommand: ``forgelab init``.

Interactively (or via flags) connects the ForgeLab MCP server to an agent:
writes/prints the right MCP config, creates the output directory, and for
Claude Code runs ``claude mcp add`` directly.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_AGENTS = ["claude-code", "hermes", "openclaw", "other"]

_CONFIG_HINTS = {
    "hermes": "Add this to your Hermes MCP configuration (the mcpServers section):",
    "openclaw": "Add this to your OpenClaw MCP configuration (the mcpServers section):",
    "other": "Add this to your agent's MCP configuration (most agents use this mcpServers shape):",
}


def _server_command() -> str:
    """Absolute path to forgelab-mcp in the running environment, if it exists."""
    candidate = Path(sys.executable).parent / "forgelab-mcp"
    return str(candidate) if candidate.exists() else "forgelab-mcp"


def _ask_agent() -> str:
    print("Which agent do you use?")
    for i, name in enumerate(_AGENTS, 1):
        print(f"  {i}. {name}")
    choice = input("Choose [1-4] (default 1): ").strip() or "1"
    try:
        return _AGENTS[int(choice) - 1]
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


def _init(agent: str, output_dir: str) -> None:
    out = Path(output_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    command = _server_command()

    print(f"✔ Output directory ready: {out}")

    if agent == "claude-code":
        add_cmd = [
            "claude", "mcp", "add", "forgelab",
            "--env", f"FORGELAB_OUTPUT_DIR={out}",
            "--", command, "--transport", "stdio",
        ]  # fmt: skip
        if shutil.which("claude"):
            subprocess.run(add_cmd, check=True)
            print("✔ Registered with Claude Code as MCP server 'forgelab'.")
            print("Next step: restart Claude Code (or run /mcp) and ask it to")
            print('  "generate a blinky LED board and export it to KiCad".')
        else:
            print("The 'claude' CLI was not found on PATH. Once Claude Code is")
            print("installed, run this yourself:")
            print(
                f"  claude mcp add forgelab --env FORGELAB_OUTPUT_DIR={out} -- "
                f"{command} --transport stdio"
            )
        return

    print(_CONFIG_HINTS[agent])
    print(_config_block(command, str(out)))
    print("Next step: restart the agent and ask it to call the ForgeLab tool")
    print("'list_domains' to confirm the connection (expected: hardware,")
    print("mechanical, threed).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="forgelab", description="ForgeLab CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="connect ForgeLab to your AI agent")
    init.add_argument("--agent", choices=_AGENTS, help="skip the interactive question")
    init.add_argument("--output-dir", help="skip the interactive question")
    args = parser.parse_args(argv)

    if args.command == "init":
        agent = args.agent or _ask_agent()
        output_dir = args.output_dir or _ask_output_dir()
        _init(agent, output_dir)


if __name__ == "__main__":
    main()
