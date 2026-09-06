"""The --no-external-tools flag itself, which nothing else would catch.

Every other test in the suite either needs a tool or does not. This file is the
only one that checks the *mechanism*, so a change to conftest that quietly stops
hiding anything shows up as a failure rather than as a suite that looks green in
both modes while only ever running one of them.
"""

import shutil

import pytest
from external_tools import EXTERNAL_TOOLS

from forgelab.formats import freecad_kernel


@pytest.fixture
def hidden(request):
    return request.config.getoption("--no-external-tools")


def test_the_flag_hides_every_listed_tool(hidden):
    if not hidden:
        pytest.skip("only meaningful under --no-external-tools")
    for tool in EXTERNAL_TOOLS:
        assert shutil.which(tool) is None, f"{tool} was still visible"


def test_the_flag_reaches_the_code_under_test(hidden):
    """Hiding is worthless unless forgelab itself sees it.

    freecad_kernel.available() is the function every FreeCAD-dependent entry
    point consults, so this is the assertion that makes the tools-hidden run
    equivalent to running on a machine without FreeCAD.
    """
    if not hidden:
        pytest.skip("only meaningful under --no-external-tools")
    assert freecad_kernel.available() is False


def test_the_flag_leaves_other_executables_alone(hidden):
    """Only the listed tools are hidden — this is a scalpel, not a blackout.

    forgelab.cli probes PATH for ``claude``, and the suite shells out to bash
    and git; blanking shutil.which wholesale would break those in ways that look
    like unrelated failures.
    """
    assert shutil.which("python3") is not None
    assert "python3" not in EXTERNAL_TOOLS
