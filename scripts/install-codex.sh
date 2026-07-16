#!/usr/bin/env bash
# One-line ForgeLab installer for Codex CLI.
#
#   curl -fsSL https://raw.githubusercontent.com/andresparraarze/ForgeLab/main/scripts/install-codex.sh | bash
#
# Thin wrapper: runs the generic installer (scripts/install.sh — venv at
# ~/.forgelab, forgelab[mcp,agent], ~/forgelab-output, PATH), then registers
# the MCP server with Codex CLI (stdio). Standalone: no prior ForgeLab or
# Claude Code install required.

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

# 2. Register with Codex CLI
step "Registering MCP server with Codex CLI"
command -v codex >/dev/null 2>&1 \
  || fail "The 'codex' CLI was not found. Install Codex CLI first, then re-run."
codex mcp remove forgelab >/dev/null 2>&1 || true
codex mcp add forgelab --env "FORGELAB_OUTPUT_DIR=$FORGELAB_OUTPUT_DIR" -- \
  "$VENV/bin/forgelab-mcp" --transport stdio \
  || fail "codex mcp add failed."
ok "registered as MCP server 'forgelab'"

echo
ok "Done! Run /mcp inside a Codex session to confirm ForgeLab's tools are listed, then try:"
echo "    \"Generate a blinky LED board and export it to KiCad as blinky.kicad_pcb\""
echo "  Exports land in: $FORGELAB_OUTPUT_DIR"
echo "  Note: generate_document needs ANTHROPIC_API_KEY available to the server."
