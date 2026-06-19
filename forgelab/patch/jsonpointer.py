"""RFC 6901 JSON Pointer — parse and resolve pointer strings (stdlib only)."""

from __future__ import annotations

from typing import Any

from forgelab.patch.errors import PatchError


def unescape_token(token: str) -> str:
    """Decode a reference token: ``~1`` -> ``/`` then ``~0`` -> ``~`` (order matters)."""
    return token.replace("~1", "/").replace("~0", "~")


def escape_token(token: str) -> str:
    """Encode a reference token: ``~`` -> ``~0`` then ``/`` -> ``~1`` (order matters)."""
    return token.replace("~", "~0").replace("/", "~1")


def parse_pointer(pointer: str) -> list[str]:
    """Split a JSON Pointer into decoded reference tokens.

    The empty pointer ``""`` points at the whole document (no tokens). Any other
    pointer must begin with ``/``.
    """
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PatchError(f"invalid JSON Pointer {pointer!r}: must be '' or start with '/'")
    return [unescape_token(token) for token in pointer.split("/")[1:]]


def array_index(array: list[Any], token: str, *, allow_end: bool) -> int:
    """Resolve a reference token to a list index.

    ``allow_end`` permits the one-past-the-end position (``len(array)`` and the
    ``"-"`` token) for insertion via ``add``.
    """
    if token == "-":
        if allow_end:
            return len(array)
        raise PatchError("array index '-' (end of array) is only valid for an 'add'")
    if token != "0" and (not token.isdigit() or token[0] == "0"):
        raise PatchError(f"invalid array index {token!r}")
    index = int(token)
    limit = len(array) if allow_end else len(array) - 1
    if index > limit:
        raise PatchError(f"array index {index} is out of range")
    return index


def get_child(container: Any, token: str) -> Any:
    """Return the child of ``container`` named by a single reference ``token``."""
    if isinstance(container, list):
        return container[array_index(container, token, allow_end=False)]
    if isinstance(container, dict):
        if token not in container:
            raise PatchError(f"member {token!r} not found")
        return container[token]
    raise PatchError(f"cannot descend into a non-container value at token {token!r}")


def resolve(document: Any, pointer: str) -> Any:
    """Return the value in ``document`` referenced by ``pointer`` (RFC 6901)."""
    current = document
    for token in parse_pointer(pointer):
        current = get_child(current, token)
    return current
