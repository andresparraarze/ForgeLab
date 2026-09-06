"""scripts/check.sh is the single definition of the gates — hold it to that.

CI and this repository's developer machines ran different checks twice in one
afternoon, and both times it was found by pushing. The script exists so a
command is written down once; these tests exist so it stays that way.
"""

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts/check.sh"
_WORKFLOW = _ROOT / ".github/workflows/ci.yml"

#: Gate names the script declares in its ALL_GATES array.
_DECLARED = re.search(r"ALL_GATES=\(([^)]*)\)", _SCRIPT.read_text()).group(1).split()

#: Gate names CI actually invokes.
_INVOKED = re.findall(r"scripts/check\.sh\s+([\w-]+)", _WORKFLOW.read_text())


def test_the_script_is_executable():
    assert _SCRIPT.stat().st_mode & 0o111, "scripts/check.sh must be chmod +x for CI to run it"


@pytest.mark.parametrize("gate", _INVOKED)
def test_every_gate_ci_invokes_exists(gate):
    """A typo in the workflow must fail here, not on a push."""
    assert gate in _DECLARED, f"ci.yml runs unknown gate {gate!r}; script has {_DECLARED}"


def test_ci_runs_every_gate_the_script_defines():
    """A gate nobody runs is worse than no gate: it reads as covered.

    If a new gate is deliberately local-only, this test is the place to say so
    explicitly rather than letting it drift out of CI unnoticed.
    """
    assert set(_INVOKED) == set(_DECLARED)


def test_ci_does_not_run_the_tools_directly():
    """Every check goes through the script, or the two can diverge again.

    A bare `run: pytest` in the workflow would look identical in the UI and
    quietly stop matching what `scripts/check.sh` runs locally.
    """
    for line in _WORKFLOW.read_text().splitlines():
        run = line.strip()
        if not run.startswith("run:"):
            continue
        command = run[len("run:") :].strip()
        first = command.split()[0] if command else ""
        assert first not in {"ruff", "pyright", "pytest"}, (
            f"ci.yml invokes {first!r} directly; call scripts/check.sh instead"
        )


def test_an_unknown_gate_is_rejected():
    """Failing loudly beats silently checking nothing."""
    result = subprocess.run(
        ["bash", str(_SCRIPT), "not-a-gate"], capture_output=True, text=True, timeout=60
    )
    assert result.returncode != 0
    assert "unknown gate" in result.stderr
