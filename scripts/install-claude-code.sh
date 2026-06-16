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

# --- PATH setup (kept above the install steps so the test suite can source
#     this file and exercise it in isolation) ---------------------------------

# Where zsh actually reads its dotfiles. Arch/EndeavourOS (and any setup using
# grml or a relocated config) point $ZDOTDIR at e.g. ~/.config/zsh from
# /etc/zsh/zshenv or ~/.zshenv, so a bare ~/.zshrc is never sourced. .zshenv is
# read for every zsh invocation, so asking zsh itself resolves it reliably.
forgelab_zsh_dir() {
  if command -v zsh >/dev/null 2>&1; then
    local d
    d="$(zsh -c 'print -rn -- ${ZDOTDIR:-$HOME}' 2>/dev/null || true)"
    if [ -n "$d" ]; then printf '%s' "$d"; return; fi
  fi
  printf '%s' "${ZDOTDIR:-$HOME}"
}

# Append a line to an rc file once (idempotent), creating it if needed.
forgelab_add_path_line() {
  local rc="$1" line="$2"
  [ -n "$rc" ] || return 0
  mkdir -p "$(dirname "$rc")" 2>/dev/null || true
  if grep -qsF "$line" "$rc"; then
    ok "already in $rc"
  else
    printf '\n# Added by the ForgeLab installer\n%s\n' "$line" >> "$rc"
    ok "added to $rc"
  fi
}

# Put a venv bin dir on PATH for future shells and the current one.
forgelab_setup_path() {
  local bindir="$1"
  local line; line="export PATH=\"$bindir:\$PATH\""
  local zdir; zdir="$(forgelab_zsh_dir)"
  # Interactive zsh reads .zshrc; login zsh — terminal emulators set to run a
  # login shell, SSH sessions, display managers — reads .zprofile. Write both
  # so the PATH survives every kind of new session without a manual re-source.
  forgelab_add_path_line "$zdir/.zshrc" "$line"
  forgelab_add_path_line "$zdir/.zprofile" "$line"
  # bash: interactive non-login reads .bashrc (only touch it if it exists, so
  # we don't conjure a bashrc on a zsh-only machine).
  [ -f "$HOME/.bashrc" ] && forgelab_add_path_line "$HOME/.bashrc" "$line"
  export PATH="$bindir:$PATH"
}

# When sourced by the test suite, stop here — only the helpers above are wanted.
if (return 0 2>/dev/null) && [ -n "${FORGELAB_INSTALLER_TEST:-}" ]; then
  return 0
fi

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

# 6. Put forgelab / forgelab-mcp / forgelab init on the PATH
step "Adding $VENV/bin to your PATH"
PATH_LINE="export PATH=\"$VENV/bin:\$PATH\""
forgelab_setup_path "$VENV/bin"
command -v forgelab >/dev/null 2>&1 || fail "forgelab not found on PATH after update."
ZSH_DIR="$(forgelab_zsh_dir)"
ok "PATH updated — 'forgelab', 'forgelab-mcp' are now global commands"
if [ "$ZSH_DIR" != "$HOME" ]; then
  echo "  (zsh dotfiles live in $ZSH_DIR — updated $ZSH_DIR/.zshrc and .zprofile)"
fi
echo "  (Current shell: run this once if the commands aren't found yet:)"
echo "    $PATH_LINE"

echo
ok "Done! Restart Claude Code (or run /mcp) and try:"
echo "    \"Generate a blinky LED board and export it to KiCad as blinky.kicad_pcb\""
echo "  Exports land in: $OUTPUT_DIR"
echo "  Note: generate_document needs ANTHROPIC_API_KEY available to the server."
