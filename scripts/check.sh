#!/usr/bin/env bash
# The gates. One definition, run by developers and by CI alike.
#
# .github/workflows/ci.yml calls `scripts/check.sh <gate>` for each of its named
# steps, so a command is written down in exactly one place. That is deliberate:
# CI and this machine drifted apart twice in one afternoon — different ruff and
# pyright versions, and a suite that ran its FreeCAD half here and its
# FreeCAD-less half there — and each time the divergence was only discovered by
# pushing.
#
# Usage:
#   scripts/check.sh            # every gate, in order
#   scripts/check.sh types      # just one
#   scripts/check.sh lint tests # a few
#
# Gates:
#   lint        ruff check
#   format      ruff format --check
#   types       pyright
#   tests       pytest
#   tests-bare  pytest with FreeCAD and kicad-cli hidden
#
# tests-bare is the one worth understanding. FreeCAD and kicad-cli are installed
# on developer machines and never in CI, so the code paths taken when they are
# absent are unreachable here without it. That gap is what let a mechanical
# preview leak the wrong exception type past a green local suite and break all
# four CI interpreters. In CI it is close to a no-op, and runs anyway so the
# flag itself is covered.

set -euo pipefail

cd "$(dirname "$0")/.."

ALL_GATES=(lint format types tests tests-bare)

run_gate() {
  case "$1" in
    lint)       ruff check . ;;
    format)     ruff format --check . ;;
    types)      pyright ;;
    tests)      pytest ;;
    tests-bare) pytest --no-external-tools ;;
    *)
      echo "unknown gate: $1" >&2
      echo "gates: ${ALL_GATES[*]}" >&2
      return 2
      ;;
  esac
}

gates=("$@")
if [ ${#gates[@]} -eq 0 ]; then
  gates=("${ALL_GATES[@]}")
fi

for gate in "${gates[@]}"; do
  echo "==> $gate"
  run_gate "$gate"
done

echo "==> all gates passed"
