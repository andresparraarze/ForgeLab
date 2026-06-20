"""Read the embedded ForgeLab hash back out of a native file.

Mirrors how each exporter embeds it: a KiCad board ``property``, a glTF
``asset.extras`` key, and a ``Hash`` attribute on the FreeCAD sidecar's
``Document`` element. Returns ``None`` when no hash is present (e.g. an older
file, or a format that cannot carry one).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from forgelab.formats import parse, read_archive_entry
from forgelab.sync.hashing import HASH_KEY

# FreeCAD sidecar entry + the attribute the exporter sets on its root element.
_FREECAD_SIDECAR = "ForgeLab.Document.xml"
_FREECAD_HASH_ATTR = "Hash"

# Map a native-file suffix to the registered tool name.
_SUFFIX_TO_TOOL = {
    ".kicad_pcb": "kicad",
    ".gltf": "gltf",
    ".fcstd": "freecad",
}


def tool_for_path(native_path: str) -> str | None:
    """Infer the format tool from a native file's extension (case-insensitive)."""
    lower = native_path.lower()
    for suffix, tool in _SUFFIX_TO_TOOL.items():
        if lower.endswith(suffix):
            return tool
    return None


def read_native_hash(tool: str, content: bytes) -> str | None:
    """Extract the embedded ForgeLab hash from native ``content`` for ``tool``."""
    if tool == "kicad":
        return _read_kicad(content)
    if tool == "gltf":
        return _read_gltf(content)
    if tool == "freecad":
        return _read_freecad(content)
    return None


def _read_kicad(content: bytes) -> str | None:
    try:
        tree = parse(content.decode("utf-8"))
    except Exception:
        return None
    for element in tree:
        if (
            isinstance(element, list)
            and len(element) >= 3
            and str(element[0]) == "property"
            and element[1] == HASH_KEY
        ):
            return str(element[2])
    return None


def _read_gltf(content: bytes) -> str | None:
    try:
        gltf = json.loads(content.decode("utf-8"))
    except Exception:
        return None
    extras = gltf.get("asset", {}).get("extras", {})
    value = extras.get(HASH_KEY)
    return str(value) if value is not None else None


def _read_freecad(content: bytes) -> str | None:
    sidecar = read_archive_entry(content, _FREECAD_SIDECAR)
    if sidecar is None:
        return None
    try:
        root = ET.fromstring(sidecar)
    except ET.ParseError:
        return None
    return root.get(_FREECAD_HASH_ATTR)
