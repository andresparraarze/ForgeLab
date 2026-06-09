"""Neutral FCStd (FreeCAD) container + Document.xml codec.

FCStd files are ZIP archives whose ``Document.xml`` describes a flat, ordered
list of objects, each with typed properties. This module reads and writes a
canonical subset of that format using only the standard library, so no FreeCAD
installation is required. It is vocabulary-agnostic: the mapping between these
generic objects and ForgeLab's typed mechanical models lives in the FreeCAD
importer/exporter, not here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

_DOCUMENT_XML = "Document.xml"
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # fixed timestamp -> deterministic output


class FcstdError(ValueError):
    """Raised when an FCStd container or Document.xml cannot be read/written."""


@dataclass
class FcProperty:
    """A single typed property of an object."""

    name: str
    ptype: str
    value: Any


@dataclass
class FcObject:
    """One FreeCAD object: a name, a type, and an ordered property list."""

    name: str
    obj_type: str
    properties: list[FcProperty] = field(default_factory=list)


@dataclass
class FcDocument:
    """A parsed FCStd document: ordered objects plus document metadata."""

    objects: list[FcObject] = field(default_factory=list)
    name: str = ""
    generator: str = ""


def _fmt_float(value: float) -> str:
    return repr(float(value))


def _floats(text: str) -> list[float]:
    text = text.strip()
    if not text:
        return []
    return [float(part) for part in text.split(",")]


def _encode_property(parent: ET.Element, prop: FcProperty) -> None:
    el = ET.SubElement(parent, "Property", {"name": prop.name, "type": prop.ptype})
    if prop.ptype in ("String", "Link"):
        el.set("value", str(prop.value))
    elif prop.ptype == "Float":
        el.set("value", _fmt_float(prop.value))
    elif prop.ptype == "Integer":
        el.set("value", str(int(prop.value)))
    elif prop.ptype == "Bool":
        el.set("value", "true" if prop.value else "false")
    elif prop.ptype == "Placement":
        pos = prop.value["position"]
        rot = prop.value["rotation"]
        for key, val in zip(("px", "py", "pz", "qx", "qy", "qz", "qw"), (*pos, *rot), strict=True):
            el.set(key, _fmt_float(val))
    elif prop.ptype == "GeometryList":
        for geo in prop.value:
            ET.SubElement(
                el,
                "Geo",
                {
                    "geo_type": geo["geo_type"],
                    "points": ",".join(_fmt_float(x) for x in geo.get("points", [])),
                    "center": ",".join(_fmt_float(x) for x in geo.get("center", [])),
                    "radius": _fmt_float(geo.get("radius", 0.0)),
                },
            )
    elif prop.ptype == "ConstraintList":
        for con in prop.value:
            ET.SubElement(
                el,
                "Constraint",
                {
                    "ctype": con["ctype"],
                    "value": _fmt_float(con["value"]),
                    "name": con.get("name", ""),
                },
            )
    else:
        raise FcstdError(f"Unsupported property type {prop.ptype!r}")


def _decode_property(el: ET.Element) -> FcProperty:
    name = el.get("name")
    ptype = el.get("type")
    if name is None or ptype is None:
        raise FcstdError("Property element missing name/type")
    if ptype in ("String", "Link"):
        value: Any = el.get("value", "")
    elif ptype == "Float":
        value = float(el.get("value", "0"))
    elif ptype == "Integer":
        value = int(el.get("value", "0"))
    elif ptype == "Bool":
        value = el.get("value") == "true"
    elif ptype == "Placement":
        value = {
            "position": [float(el.get(k, "0")) for k in ("px", "py", "pz")],
            "rotation": [float(el.get(k, "0")) for k in ("qx", "qy", "qz", "qw")],
        }
    elif ptype == "GeometryList":
        value = [
            {
                "geo_type": g.get("geo_type", ""),
                "points": _floats(g.get("points", "")),
                "center": _floats(g.get("center", "")),
                "radius": float(g.get("radius", "0")),
            }
            for g in el.findall("Geo")
        ]
    elif ptype == "ConstraintList":
        value = [
            {
                "ctype": c.get("ctype", ""),
                "value": float(c.get("value", "0")),
                "name": c.get("name", ""),
            }
            for c in el.findall("Constraint")
        ]
    else:
        raise FcstdError(f"Unsupported property type {ptype!r}")
    return FcProperty(name=name, ptype=ptype, value=value)


def _build_document_xml(document: FcDocument) -> bytes:
    root = ET.Element(
        "Document",
        {
            "SchemaVersion": "4",
            "ProgramVersion": "ForgeLab",
            "DocName": document.name,
            "DocGenerator": document.generator,
        },
    )
    objects_el = ET.SubElement(root, "Objects", {"Count": str(len(document.objects))})
    for obj in document.objects:
        ET.SubElement(objects_el, "Object", {"type": obj.obj_type, "name": obj.name})
    data_el = ET.SubElement(root, "ObjectData", {"Count": str(len(document.objects))})
    for obj in document.objects:
        od = ET.SubElement(data_el, "Object", {"name": obj.name})
        props_el = ET.SubElement(od, "Properties", {"Count": str(len(obj.properties))})
        for prop in obj.properties:
            _encode_property(props_el, prop)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_fcstd(document: FcDocument) -> bytes:
    """Serialize an FcDocument to deterministic FCStd (ZIP) bytes."""
    document_xml = _build_document_xml(document)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo(_DOCUMENT_XML, date_time=_ZIP_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, document_xml)
    return buffer.getvalue()


def read_document(data: bytes) -> FcDocument:
    """Parse FCStd bytes into an FcDocument. Raises FcstdError on bad input."""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FcstdError("Not a valid FCStd (ZIP) archive") from exc
    with archive:
        try:
            document_xml = archive.read(_DOCUMENT_XML)
        except KeyError as exc:
            raise FcstdError("FCStd archive has no Document.xml") from exc

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise FcstdError(f"Malformed Document.xml: {exc}") from exc

    objects_el = root.find("Objects")
    data_el = root.find("ObjectData")
    if objects_el is None or data_el is None:
        raise FcstdError("Document.xml missing Objects/ObjectData")

    order: list[tuple[str, str]] = []
    for obj in objects_el.findall("Object"):
        name = obj.get("name")
        obj_type = obj.get("type")
        if name is None or obj_type is None:
            raise FcstdError("Object in Objects missing name/type")
        order.append((name, obj_type))

    props_by_name: dict[str, list[FcProperty]] = {}
    for obj in data_el.findall("Object"):
        name = obj.get("name")
        if name is None:
            raise FcstdError("Object in ObjectData missing name")
        props_el = obj.find("Properties")
        props_by_name[name] = (
            [_decode_property(p) for p in props_el.findall("Property")]
            if props_el is not None
            else []
        )

    objects = [
        FcObject(name=name, obj_type=obj_type, properties=props_by_name.get(name, []))
        for name, obj_type in order
    ]
    return FcDocument(
        objects=objects,
        name=root.get("DocName", ""),
        generator=root.get("DocGenerator", ""),
    )


def read_objects(data: bytes) -> list[FcObject]:
    """Convenience: parse FCStd bytes and return only the object list."""
    return read_document(data).objects
