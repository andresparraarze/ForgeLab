"""Parse genuine FreeCAD ``Document.xml`` into ForgeLab mechanical props.

Best-effort canonical-subset reader for real FreeCAD files: App::Part,
PartDesign::Body, Sketcher::SketchObject (line/circle geometry, dimensional
constraints), PartDesign::Pad and PartDesign::Pocket. Unknown object types are
skipped (real FreeCAD documents carry Origin planes/axes and other objects the
ForgeLab vocabulary does not model). Depends only on stdlib + forgelab.spec.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

# FreeCAD Sketcher::Constraint numeric Type -> name (subset with a value).
_CONSTRAINT_TYPES = {
    "6": "Distance",
    "7": "DistanceX",
    "8": "DistanceY",
    "9": "Angle",
    "11": "Radius",
    "18": "Diameter",
}

_KNOWN_TYPES = {
    "App::Part": "part",
    "PartDesign::Body": "body",
    "Sketcher::SketchObject": "sketch",
    "PartDesign::Pad": "pad",
    "PartDesign::Pocket": "pocket",
}


def _prop_el(obj: ET.Element, name: str) -> ET.Element | None:
    props = obj.find("Properties")
    if props is None:
        return None
    for p in props.findall("Property"):
        if p.get("name") == name:
            return p
    return None


def _string(obj: ET.Element, name: str, default: str = "") -> str:
    p = _prop_el(obj, name)
    if p is None:
        return default
    el = p.find("String")
    return el.get("value", default) if el is not None else default


def _float(obj: ET.Element, name: str, default: float = 0.0) -> float:
    p = _prop_el(obj, name)
    if p is None:
        return default
    el = p.find("Float")
    return float(el.get("value", default)) if el is not None else default


def _bool(obj: ET.Element, name: str, default: bool = False) -> bool:
    p = _prop_el(obj, name)
    if p is None:
        return default
    el = p.find("Bool")
    return (el.get("value") == "true") if el is not None else default


def _int(obj: ET.Element, name: str, default: int = 0) -> int:
    p = _prop_el(obj, name)
    if p is None:
        return default
    el = p.find("Integer")
    return int(el.get("value", default)) if el is not None else default


def _link(obj: ET.Element, name: str) -> str:
    p = _prop_el(obj, name)
    if p is None:
        return ""
    el = p.find("Link") or p.find("LinkSub")
    return el.get("value", "") if el is not None else ""


def _link_list(obj: ET.Element, name: str) -> list[str]:
    p = _prop_el(obj, name)
    if p is None:
        return []
    ll = p.find("LinkList")
    if ll is None:
        return []
    return [link.get("value", "") for link in ll.findall("Link")]


def _placement(obj: ET.Element) -> dict[str, Any]:
    p = _prop_el(obj, "Placement")
    el = p.find("PropertyPlacement") if p is not None else None
    if el is None:
        return {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0]}

    def g(key: str, default: float) -> float:
        return float(el.get(key, default))

    return {
        "position": [g("Px", 0), g("Py", 0), g("Pz", 0)],
        "rotation": [g("Q0", 0), g("Q1", 0), g("Q2", 0), g("Q3", 1)],
    }


def _geometry(obj: ET.Element) -> list[dict[str, Any]]:
    p = _prop_el(obj, "Geometry")
    gl = p.find("GeometryList") if p is not None else None
    out: list[dict[str, Any]] = []
    if gl is None:
        return out
    for geo in gl.findall("Geometry"):
        line = geo.find("LineSegment")
        circ = geo.find("Circle")
        if line is not None:
            out.append(
                {
                    "geo_type": "line",
                    "points": [
                        float(line.get("StartX", 0)),
                        float(line.get("StartY", 0)),
                        float(line.get("EndX", 0)),
                        float(line.get("EndY", 0)),
                    ],
                    "center": [],
                    "radius": 0.0,
                }
            )
        elif circ is not None:
            out.append(
                {
                    "geo_type": "circle",
                    "points": [],
                    "center": [float(circ.get("CenterX", 0)), float(circ.get("CenterY", 0))],
                    "radius": float(circ.get("Radius", 0)),
                }
            )
    return out


def _constraints(obj: ET.Element) -> list[dict[str, Any]]:
    p = _prop_el(obj, "Constraints")
    cl = p.find("ConstraintList") if p is not None else None
    out: list[dict[str, Any]] = []
    if cl is None:
        return out
    for c in cl.findall("Constrain"):
        ctype = _CONSTRAINT_TYPES.get(c.get("Type", ""))
        if ctype is None:
            continue  # geometric (valueless) constraints are not modeled
        out.append(
            {
                "ctype": ctype,
                "value": float(c.get("Value", 0.0)),
                "name": c.get("Name", "") or "",
            }
        )
    return out


def parse_real_document(root: ET.Element) -> list[tuple[str, str, dict[str, Any]]]:
    """Extract (name, node_type, props) from a real FreeCAD Document root."""
    objects_el = root.find("Objects")
    data_el = root.find("ObjectData")
    if objects_el is None or data_el is None:
        return []
    type_of = {o.get("name", ""): o.get("type", "") for o in objects_el.findall("Object")}
    data_of = {o.get("name", ""): o for o in data_el.findall("Object")}

    # Reverse membership: feature -> owning body, body -> owning part.
    body_of: dict[str, str] = {}
    part_of: dict[str, str] = {}
    for name, fc_type in type_of.items():
        obj = data_of.get(name)
        if obj is None:
            continue
        if fc_type == "PartDesign::Body":
            for member in _link_list(obj, "Group"):
                body_of[member] = name
        elif fc_type == "App::Part":
            for member in _link_list(obj, "Group"):
                part_of[member] = name

    items: list[tuple[str, str, dict[str, Any]]] = []
    for name, fc_type in type_of.items():
        node_type = _KNOWN_TYPES.get(fc_type)
        obj = data_of.get(name)
        if node_type is None or obj is None:
            continue  # skip Origin planes/axes and other unmodeled objects
        label = _string(obj, "Label", name)
        props: dict[str, Any]
        if node_type == "part":
            props = {"name": label, "placement": _placement(obj)}
        elif node_type == "body":
            props = {
                "name": label,
                "part": part_of.get(name, ""),
                "placement": _placement(obj),
            }
        elif node_type == "sketch":
            props = {
                "name": label,
                "body": body_of.get(name, ""),
                "plane": "XY_Plane",
                "placement": _placement(obj),
                "geometry": _geometry(obj),
                "constraints": _constraints(obj),
            }
        else:  # pad / pocket
            props = {
                "name": label,
                "body": body_of.get(name, ""),
                "profile": _link(obj, "Profile"),
                "length": _float(obj, "Length"),
                "reversed": _bool(obj, "Reversed"),
                "midplane": _bool(obj, "Midplane"),
            }
            if node_type == "pocket":
                props["through_all"] = _int(obj, "Type") == 1
        items.append((name, node_type, props))
    return items
