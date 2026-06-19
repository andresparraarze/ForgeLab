"""Generate an RFC 6902 patch that transforms one JSON document into another.

The result is a correct (not necessarily minimal) patch using add/remove/replace
such that ``apply_patch(source, diff(source, target)) == target``.
"""

from __future__ import annotations

import copy
from typing import Any

from forgelab.patch.jsonpointer import escape_token


def diff(source: Any, target: Any) -> list[dict[str, Any]]:
    """RFC 6902 patch transforming ``source`` into ``target``."""
    ops: list[dict[str, Any]] = []
    _diff(source, target, "", ops)
    return ops


def _diff(a: Any, b: Any, pointer: str, ops: list[dict[str, Any]]) -> None:
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        _diff_dict(a, b, pointer, ops)
        return
    if isinstance(a, list) and isinstance(b, list):
        _diff_list(a, b, pointer, ops)
        return
    # Scalars that differ, or a container-type change: replace the value outright.
    ops.append({"op": "replace", "path": pointer if pointer else "", "value": copy.deepcopy(b)})


def _diff_dict(a: dict, b: dict, pointer: str, ops: list[dict[str, Any]]) -> None:
    for key in a:
        child = f"{pointer}/{escape_token(key)}"
        if key not in b:
            ops.append({"op": "remove", "path": child})
        else:
            _diff(a[key], b[key], child, ops)
    for key in b:
        if key not in a:
            child = f"{pointer}/{escape_token(key)}"
            ops.append({"op": "add", "path": child, "value": copy.deepcopy(b[key])})


def _diff_list(a: list, b: list, pointer: str, ops: list[dict[str, Any]]) -> None:
    common = min(len(a), len(b))
    for i in range(common):
        _diff(a[i], b[i], f"{pointer}/{i}", ops)
    # Trim surplus tail elements from the highest index down so indices stay valid.
    for i in range(len(a) - 1, len(b) - 1, -1):
        ops.append({"op": "remove", "path": f"{pointer}/{i}"})
    # Append new tail elements in order (each add lands at the current end).
    for i in range(len(a), len(b)):
        ops.append({"op": "add", "path": f"{pointer}/{i}", "value": copy.deepcopy(b[i])})
