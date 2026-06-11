#!/usr/bin/env bash
# One-line ForgeLab installer for Claude Code.
#
#   curl -fsSL https://raw.githubusercontent.com/andresparraarze/ForgeLab/main/scripts/install-claude-code.sh | bash
#
# Creates a venv in ~/.forgelab, installs forgelab[mcp,agent], registers the
# MCP server with Claude Code (stdio), and sets up ~/forgelab-output.

set -euo pipefail

FORGELAB_HOME="${FORGELAB_HOME:-$HOME/.forgelab}"
VENV="$FORGELAB_HOME/venv"
OUTPUT_DIR="${FORGELAB_OUTPUT_DIR:-$HOME/forgelab-output}"
REPO_URL="https://github.com/andresparraarze/ForgeLab"

ok()   { printf '\033[32m✔\033[0m %s\n' "$1"; }
fail() { printf '\033[31m✘ %s\033[0m\n' "$1" >&2; exit 1; }
step() { printf '\033[36m→ %s\033[0m\n' "$1"; }

# 1. Python 3.11+
step "Checking Python"
PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || fail "python3 not found. Install Python 3.11+ and re-run."
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python 3.11+ required (found $("$PYTHON" --version))."
ok "Python OK: $("$PYTHON" --version)"

# 2. venv
step "Creating venv at $VENV"
mkdir -p "$FORGELAB_HOME"
"$PYTHON" -m venv "$VENV" || fail "Could not create venv at $VENV."
ok "venv ready"

# 3. Install forgelab[mcp,agent] — from this checkout if the script lives in
#    the repo, otherwise straight from GitHub.
step "Installing forgelab[mcp,agent]"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../pyproject.toml" ]; then
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -e "$SCRIPT_DIR/..[mcp,agent]" \
    || fail "pip install from local checkout failed."
else
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet "forgelab[mcp,agent] @ git+$REPO_URL" \
    || fail "pip install from $REPO_URL failed."
fi
[ -x "$VENV/bin/forgelab-mcp" ] || fail "forgelab-mcp not found in the venv after install."
ok "forgelab installed ($("$VENV/bin/python" -c 'import forgelab.spec; print("spec", forgelab.spec.SPEC_VERSION)'))"

# 4. Output directory
step "Creating output directory $OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR" || fail "Could not create $OUTPUT_DIR."
ok "output directory ready"

# 5. Register with Claude Code
step "Registering MCP server with Claude Code"
command -v claude >/dev/null 2>&1 \
  || fail "The 'claude' CLI was not found. Install Claude Code first, then re-run."
claude mcp remove forgelab >/dev/null 2>&1 || true
claude mcp add forgelab --env "FORGELAB_OUTPUT_DIR=$OUTPUT_DIR" -- \
  "$VENV/bin/forgelab-mcp" --transport stdio \
  || fail "claude mcp add failed."
ok "registered as MCP server 'forgelab'"

echo
ok "Done! Restart Claude Code (or run /mcp) and try:"
echo "    \"Generate a blinky LED board and export it to KiCad as blinky.kicad_pcb\""
echo "  Exports land in: $OUTPUT_DIR"
echo "  Note: generate_document needs ANTHROPIC_API_KEY available to the server."
