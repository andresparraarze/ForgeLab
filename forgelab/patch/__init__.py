"""RFC 6901 JSON Pointer + RFC 6902 JSON Patch, implemented from scratch.

Pure standard-library code (no external dependencies) so agents can mutate a
``.forge.json`` on disk with a small patch — and diff two versions — without ever
re-emitting the full document into the context window.
"""

from forgelab.patch.diff import diff
from forgelab.patch.errors import PatchError
from forgelab.patch.jsonpatch import apply_patch
from forgelab.patch.jsonpointer import parse_pointer, resolve

__all__ = ["apply_patch", "diff", "resolve", "parse_pointer", "PatchError"]
