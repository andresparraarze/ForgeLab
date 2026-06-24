"""Defaults for exporting a whole project: per-domain default tool and the
native file extension each tool writes."""

from __future__ import annotations

# The natural native target for each domain when a project export does not name a
# tool explicitly.
DEFAULT_TOOL_BY_DOMAIN = {
    "hardware": "kicad",
    "mechanical": "freecad",
    "threed": "gltf",
}

# Native file extension per registered export tool.
EXTENSION_BY_TOOL = {
    "kicad": ".kicad_pcb",
    "gltf": ".gltf",
    "freecad": ".FCStd",
    "blender_script": ".py",
    "gerber": ".gbr",
    "altium": ".PcbDoc",
    "fusion360": ".f3d",
    "blender": ".blend",
    "unreal": ".uasset",
}


def default_tool_for_domain(domain: str) -> str | None:
    """The default export tool for a domain, or None if there isn't one."""
    return DEFAULT_TOOL_BY_DOMAIN.get(domain)


def extension_for_tool(tool: str) -> str:
    """The native file extension a tool writes (falls back to ``.<tool>``)."""
    return EXTENSION_BY_TOOL.get(tool, f".{tool}")
