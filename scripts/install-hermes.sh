#!/usr/bin/env bash
# One-line ForgeLab installer for Hermes Agent.
#
#   curl -fsSL https://raw.githubusercontent.com/andresparraarze/ForgeLab/main/scripts/install-hermes.sh | bash
#
# Thin wrapper: runs the generic installer (scripts/install.sh — venv at
# ~/.forgelab, forgelab[mcp,agent,preview], ~/forgelab-output, PATH), then
# registers the MCP server with Hermes Agent over stdio. Standalone: no prior
# ForgeLab install and no other agent required.
#
# The registration itself is `forgelab init --agent hermes`, not a hand-written
# `hermes mcp add` line. These four CLIs disagree in small ways that are easy to
# copy wrong — scope defaults, how server arguments are passed, whether removal
# is spelled "remove" or "unset", whether adding prompts for confirmation — so
# the commands live in forgelab/cli.py where tests can assert them exactly.

set -euo pipefail

export FORGELAB_HOME="${FORGELAB_HOME:-$HOME/.forgelab}"
export FORGELAB_OUTPUT_DIR="${FORGELAB_OUTPUT_DIR:-$HOME/forgelab-output}"
VENV="$FORGELAB_HOME/venv"
REPO_RAW="https://raw.githubusercontent.com/andresparraarze/ForgeLab/main"

ok()   { printf '\033[32m✔\033[0m %s\n' "$1"; }
fail() { printf '\033[31m✘ %s\033[0m\n' "$1" >&2; exit 1; }
step() { printf '\033[36m→ %s\033[0m\n' "$1"; }

# 1. Generic install: use the copy next to this script when run from a
#    checkout; when piped through curl there is no script dir, so fetch it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/install.sh" ]; then
  bash "$SCRIPT_DIR/install.sh"
else
  curl -fsSL "$REPO_RAW/scripts/install.sh" | bash
fi

# 2. Register with Hermes Agent
step "Registering MCP server with Hermes Agent"
command -v hermes >/dev/null 2>&1 \
  || fail "The 'hermes' CLI was not found. Install Hermes Agent first, then re-run."
# </dev/null: under `curl ... | bash` this script *is* stdin, and a registrar
# that asks a question would otherwise swallow the rest of it.
"$VENV/bin/forgelab" init --agent hermes --output-dir "$FORGELAB_OUTPUT_DIR" </dev/null \
  || fail "forgelab init --agent hermes failed."

echo
ok "Done! Start a new Hermes session (hermes mcp list shows the server) and try:"
echo "    \"Generate a blinky LED board and export it to KiCad as blinky.kicad_pcb\""
echo "  Exports land in: $FORGELAB_OUTPUT_DIR"
echo "  Note: generate_document needs ANTHROPIC_API_KEY available to the server."
