"""Geometric verification of ForgeLab documents against the real CAD kernel.

A service package, peer to ``forgelab.preview``: it turns a document into a
native file, drives the tool that owns the geometry, and reports what actually
got built. Optional at runtime — see :func:`forgelab.verify.freecad.available`.
"""

from forgelab.verify.freecad import VerifyError, available, verify_document

__all__ = ["VerifyError", "available", "verify_document"]
