"""RFC 6902 JSON Patch — apply an operation array to a document (stdlib only).

A patch is applied to a deep copy; if any operation fails the whole patch fails
and the original document is left untouched (RFC 6902 atomicity).
"""

from __future__ import annotations

import copy
from typing import Any

from forgelab.patch.errors import PatchError
from forgelab.patch.jsonpointer import array_index, get_child, parse_pointer

_OPERATIONS = frozenset({"add", "remove", "replace", "move", "copy", "test"})


def apply_patch(document: Any, patch: list[dict[str, Any]]) -> Any:
    """Apply an RFC 6902 patch and return the new document (input is not mutated)."""
    if not isinstance(patch, list):
        raise PatchError("a JSON Patch must be an array of operations")
    result = copy.deepcopy(document)
    for index, operation in enumerate(patch):
        result = _apply_one(result, operation, index)
    return result


def _member(operation: dict[str, Any], name: str, index: int) -> Any:
    if name not in operation:
        raise PatchError(f"operation {index} ({operation.get('op')!r}) is missing {name!r}")
    return operation[name]


def _apply_one(document: Any, operation: Any, index: int) -> Any:
    if not isinstance(operation, dict):
        raise PatchError(f"operation {index} is not an object")
    op = operation.get("op")
    if op not in _OPERATIONS:
        raise PatchError(f"operation {index} has unknown op {op!r}")
    tokens = parse_pointer(_member(operation, "path", index))

    if op == "add":
        return _add(document, tokens, copy.deepcopy(_member(operation, "value", index)))
    if op == "replace":
        return _replace(document, tokens, copy.deepcopy(_member(operation, "value", index)))
    if op == "remove":
        _remove(document, tokens)
        return document
    if op == "test":
        _test(document, tokens, _member(operation, "value", index))
        return document

    # move / copy both take a 'from' pointer.
    from_tokens = parse_pointer(_member(operation, "from", index))
    if op == "copy":
        return _add(document, tokens, copy.deepcopy(_resolve_tokens(document, from_tokens)))
    # move
    if _is_proper_prefix(from_tokens, tokens):
        raise PatchError(f"operation {index} (move) cannot move a value into its own child")
    value = _remove(document, from_tokens)
    return _add(document, tokens, value)


def _resolve_tokens(document: Any, tokens: list[str]) -> Any:
    current = document
    for token in tokens:
        current = get_child(current, token)
    return current


def _parent(document: Any, tokens: list[str]) -> Any:
    parent = document
    for token in tokens[:-1]:
        parent = get_child(parent, token)
    return parent


def _add(document: Any, tokens: list[str], value: Any) -> Any:
    if not tokens:
        return value  # adding at "" replaces the whole document
    parent = _parent(document, tokens)
    token = tokens[-1]
    if isinstance(parent, list):
        parent.insert(array_index(parent, token, allow_end=True), value)
    elif isinstance(parent, dict):
        parent[token] = value
    else:
        raise PatchError(f"cannot add to a non-container value at token {token!r}")
    return document


def _replace(document: Any, tokens: list[str], value: Any) -> Any:
    if not tokens:
        return value
    parent = _parent(document, tokens)
    token = tokens[-1]
    if isinstance(parent, list):
        parent[array_index(parent, token, allow_end=False)] = value
    elif isinstance(parent, dict):
        if token not in parent:
            raise PatchError(f"cannot replace nonexistent member {token!r}")
        parent[token] = value
    else:
        raise PatchError(f"cannot replace within a non-container value at token {token!r}")
    return document


def _remove(document: Any, tokens: list[str]) -> Any:
    if not tokens:
        raise PatchError("cannot remove the whole document")
    parent = _parent(document, tokens)
    token = tokens[-1]
    if isinstance(parent, list):
        return parent.pop(array_index(parent, token, allow_end=False))
    if isinstance(parent, dict):
        if token not in parent:
            raise PatchError(f"cannot remove nonexistent member {token!r}")
        return parent.pop(token)
    raise PatchError(f"cannot remove from a non-container value at token {token!r}")


def _test(document: Any, tokens: list[str], value: Any) -> None:
    if _resolve_tokens(document, tokens) != value:
        raise PatchError("test failed: the value at the pointer does not equal the expected value")


def _is_proper_prefix(prefix: list[str], tokens: list[str]) -> bool:
    return len(prefix) < len(tokens) and tokens[: len(prefix)] == prefix
