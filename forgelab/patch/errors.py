"""Shared error type for the JSON Pointer / JSON Patch implementation."""

from __future__ import annotations


class PatchError(ValueError):
    """A JSON Pointer (RFC 6901) or JSON Patch (RFC 6902) operation failed."""
