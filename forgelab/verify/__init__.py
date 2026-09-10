"""Verification of ForgeLab documents against the real tool that owns them.

A service package, peer to ``forgelab.preview``: it turns a document into a
native file, drives the tool, and reports what that tool actually says. Both
tools are optional at runtime — see each module's ``available()``.

Two domains, two authorities. A mechanical part is built in FreeCAD's OCC kernel,
because FreeCAD reports no error for geometry that silently produces nothing. A
board is checked by KiCad's own DRC, because ForgeLab's geometric checks
deliberately stop short of reimplementing copper-pour fills, courtyards and
solder-mask bridging — and those are exactly where a plausible-looking board
turns out to be unbuildable.
"""

from forgelab.verify import kicad
from forgelab.verify.freecad import VerifyError, available, verify_document

__all__ = ["VerifyError", "available", "kicad", "verify_document"]
