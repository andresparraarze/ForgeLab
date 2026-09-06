"""Test-session configuration.

Holds one option, ``--no-external-tools``, which exists because of a red build.

FreeCAD and kicad-cli are installed on the machines this project is developed on
and on none of the CI runners. The consequence is not merely that CI skips those
tests — it is that the *degraded* paths, the ones taken when a tool is missing,
never run locally. A mechanical ``preview_render`` leaked ``FreeCADKernelError``
(then a ``RuntimeError``) instead of the ``ValueError`` every MCP tool promises;
the test asserting that passed here and failed on all four CI interpreters.

``pytest --no-external-tools`` reproduces the CI environment on a developer
machine by hiding those executables, so both halves of the suite are reachable
from one checkout. ``scripts/check.sh`` runs it as a gate.
"""

import shutil

import pytest
from external_tools import EXTERNAL_TOOLS, MISSING_REASON

_FLAG = "--no-external-tools"

#: Saved so the patch can be undone at the end of the session.
_REAL_WHICH: pytest.StashKey = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        _FLAG,
        action="store_true",
        default=False,
        help=(
            f"Hide the optional external tools ({', '.join(EXTERNAL_TOOLS)}) so the "
            f"suite runs as CI sees it. Use it to exercise the code paths taken "
            f"when a tool is absent."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the marker and, when asked, hide the tools it names.

    Patching ``shutil.which`` itself rather than setting a forgelab-level flag
    is deliberate: it is what ``freecad_kernel.available()`` actually calls, so
    the production code takes its real not-installed path instead of a simulated
    one. Only the names in ``EXTERNAL_TOOLS`` are hidden — every other lookup
    (``cli.py`` probing for ``claude``, say) still gets the true answer.
    """
    config.addinivalue_line(
        "markers",
        "external_tool(name): test needs an external tool on PATH; skipped without it.",
    )
    if not config.getoption(_FLAG):
        return
    real = shutil.which

    def which(cmd, *args, **kwargs):
        if cmd in EXTERNAL_TOOLS:
            return None
        return real(cmd, *args, **kwargs)

    config.stash[_REAL_WHICH] = real
    shutil.which = which


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip the tests whose tool is absent, deciding during collection.

    Doing it here rather than in a ``skipif`` condition is what makes the flag
    reliable: a ``skipif`` is evaluated when its module is imported, so whether
    it saw the patched ``shutil.which`` would depend on import order — and it
    did, silently, until this ran the tools-hidden suite and 34 tests failed
    instead of skipping.
    """
    for item in items:
        for marker in item.iter_markers(name="external_tool"):
            tool = marker.args[0]
            if shutil.which(tool) is None:
                item.add_marker(pytest.mark.skip(reason=MISSING_REASON[tool]))


def pytest_unconfigure(config: pytest.Config) -> None:
    real = config.stash.get(_REAL_WHICH, None)
    if real is not None:
        shutil.which = real
