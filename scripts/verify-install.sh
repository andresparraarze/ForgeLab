#!/usr/bin/env bash
# Perform a real ForgeLab install and check that the result works.
#
#   scripts/verify-install.sh [workdir]
#
# The unit tests assert what the installers *say*; this asserts what they do.
# Every defect it covers was invisible to the suite:
#
#   - `claude mcp add` defaulting to --scope local, so ForgeLab was registered
#     for one directory and missing everywhere else;
#   - forgelab[mcp,agent] shipping without matplotlib, so preview_render — one
#     of the 40 tools — failed on every clean machine while this dev box, which
#     carried an orphaned matplotlib, looked fine;
#   - a git-URL install that does not move when the source does.
#
# Runs against stub agent CLIs in a throwaway HOME, so it touches neither the
# caller's ~/.claude.json nor their shell rc files.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
WORK="${1:-$(mktemp -d)}"
HOME_DIR="$WORK/home"
STUB="$WORK/stub"
ARGV="$WORK/argv.log"

ok()   { printf '\033[32m✔\033[0m %s\n' "$1"; }
fail() { printf '\033[31m✘ %s\033[0m\n' "$1" >&2; exit 1; }
step() { printf '\033[36m→ %s\033[0m\n' "$1"; }

rm -rf "$HOME_DIR" "$STUB" "$ARGV"
mkdir -p "$HOME_DIR" "$STUB"

# Stub agent CLIs: record argv, drain stdin, succeed.
for name in claude codex hermes openclaw; do
  printf '#!/bin/sh\nprintf "%%s\\n" "%s $*" >> "%s"\ncat >/dev/null\n' "$name" "$ARGV" > "$STUB/$name"
  chmod +x "$STUB/$name"
done

VENV="$HOME_DIR/.forgelab/venv"
OUT="$HOME_DIR/out"
run_installer() {
  # HOME is redirected so the installer's rc-file edits and ~/.forgelab land in
  # the throwaway tree, and the stub CLIs go first on PATH. The rest of PATH is
  # kept, not wiped: on a CI runner the interpreter under test comes from
  # setup-python, which lives outside /usr/bin. VIRTUAL_ENV and PYTHONPATH are
  # dropped so an activated venv cannot leak into the install being measured.
  env -u VIRTUAL_ENV -u PYTHONPATH \
    "HOME=$HOME_DIR" "PATH=$STUB:$PATH" \
    "FORGELAB_HOME=$HOME_DIR/.forgelab" "FORGELAB_OUTPUT_DIR=$OUT" \
    bash "$REPO/scripts/install-$1.sh"
}

# 1. Install for Claude Code.
step "Running scripts/install-claude-code.sh"
run_installer claude-code > "$WORK/install.log" 2>&1 \
  || { cat "$WORK/install.log"; fail "installer exited non-zero"; }
ok "installer finished"

# 2. Registration must be global, not scoped to the install directory.
step "Checking MCP registration"
grep -q -- "mcp add forgelab --scope user" "$ARGV" \
  || { cat "$ARGV"; fail "claude registration is not at --scope user"; }
grep -q -- "--transport stdio" "$ARGV" || fail "claude registration is not stdio"
ok "registered at user scope over stdio"

# 3. The other three wrappers register too, each with its own flags.
for agent in codex hermes openclaw; do
  step "Running scripts/install-$agent.sh"
  run_installer "$agent" >> "$WORK/install.log" 2>&1 || fail "install-$agent.sh failed"
done
grep -q "^hermes mcp add forgelab --command" "$ARGV" || fail "hermes was not registered"
if grep "^hermes mcp add" "$ARGV" | grep -q -- "--transport"; then
  fail "hermes must pass no server arguments (--args cannot carry a leading dash)"
fi
grep -q "^openclaw mcp unset forgelab" "$ARGV" \
  || fail "openclaw removal must be 'unset'; it has no 'mcp remove'"
ok "codex, hermes and openclaw registered"

# 4. The installed server has to actually speak MCP.
step "Talking to the installed server over stdio"
"$VENV/bin/python" "$REPO/scripts/probe_install.py" "$VENV" "$REPO" "$OUT" \
  || fail "the installed server did not answer"
ok "40 tools, list_domains and preview_render all answered"

# 5. A git-URL install must move when the source does. This is the one thing a
#    unit test cannot fake, and the reason `forgelab update` exists at all.
if git -C "$REPO" rev-parse HEAD~1 >/dev/null 2>&1; then
  step "Upgrading a git-URL install across two commits"
  UPD="$WORK/upgrade"
  rm -rf "$UPD"
  python3 -m venv "$UPD"
  "$UPD/bin/pip" install --quiet --upgrade pip
  OLD_REV="$(git -C "$REPO" rev-parse HEAD~1)"
  NEW_REV="$(git -C "$REPO" rev-parse HEAD)"
  "$UPD/bin/pip" install --quiet "forgelab[mcp,agent,preview] @ git+file://$REPO@$OLD_REV"
  before="$("$UPD/bin/python" -c 'import forgelab; print(forgelab.__version__)')"
  "$UPD/bin/pip" install --quiet --upgrade "forgelab[mcp,agent,preview] @ git+file://$REPO@$NEW_REV"
  after="$("$UPD/bin/python" -c 'import forgelab; print(forgelab.__version__)')"
  [ "$before" != "$after" ] \
    || fail "a plain --upgrade left the install at $before; it did not move"
  ok "upgraded $before -> $after"
else
  echo "  (skipping the upgrade check: no HEAD~1 in this checkout)"
fi

ok "install verified"
