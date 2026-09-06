"""Markers for tests that need one of the external tools ForgeLab drives.

ForgeLab treats FreeCAD and KiCad as *ground truth* rather than as libraries: a
mechanical part is verified by building it in the real OCC kernel, and a board
is checked by running kicad-cli's own DRC. Neither is a Python dependency, so
neither can be installed by pip, and CI runs without them.

Marking rather than skipping is the point. A ``pytest.mark.skipif`` decides at
import time, which makes the answer depend on when a module happens to be
imported; these marks only *declare* which tool a test needs, and conftest
decides during collection — after ``--no-external-tools`` has been applied. See
conftest.py for the other side of it.
"""

import pytest

#: The executables ForgeLab shells out to. ``conftest`` hides exactly these
#: under ``--no-external-tools``; nothing else on PATH is affected.
EXTERNAL_TOOLS = ("freecadcmd", "kicad-cli")

#: Reason text shown when a tool is absent, keyed by executable.
MISSING_REASON = {
    "freecadcmd": "FreeCAD is not installed (freecadcmd not on PATH)",
    "kicad-cli": "kicad-cli is not installed",
}

requires_freecad = pytest.mark.external_tool("freecadcmd")
requires_kicad_cli = pytest.mark.external_tool("kicad-cli")
