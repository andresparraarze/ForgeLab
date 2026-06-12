"""End-to-end FreeCAD validation: exported FCStd genuinely opens in FreeCAD.

Runs only where FreeCAD is installed (``freecadcmd`` on PATH); skipped in CI.
"""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("freecadcmd") is None, reason="FreeCAD is not installed"
)

_CHECK = textwrap.dedent(
    """
    import FreeCAD as App
    doc = App.openDocument({path!r})
    for o in doc.Objects:
        o.touch()
    doc.recompute()
    bad = [o.Name for o in doc.Objects if o.State and "Invalid" in str(o.State)]
    print("BAD:", bad)
    pocket = doc.getObject("Pocket")
    print("VALID:", pocket.Shape.isValid())
    print("VOLUME:", round(pocket.Shape.Volume, 2))
    """
)


def test_exported_example_opens_and_recomputes_in_freecad(tmp_path):
    example = Path("examples/mechanical/box-with-hole.FCStd").resolve()
    script = tmp_path / "check.py"
    script.write_text(_CHECK.format(path=str(example)))
    result = subprocess.run(
        ["freecadcmd", str(script)], capture_output=True, text=True, timeout=120
    )
    out = result.stdout
    assert "BAD: []" in out, f"objects failed to recompute:\n{out}\n{result.stderr}"
    assert "VALID: True" in out
    # 40*20*10 box minus a radius-4 through hole: 8000 - pi*16*10 = 7497.35
    assert "VOLUME: 7497.35" in out
