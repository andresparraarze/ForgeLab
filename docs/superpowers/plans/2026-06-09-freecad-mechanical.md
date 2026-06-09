# FreeCAD Mechanical CAD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Mechanical CAD domain to ForgeLab via a stdlib-only FreeCAD `.FCStd` importer/exporter with an IR-level round-trip identity guarantee, typed mechanical spec models, a box-with-hole example, and AI-SDK wiring — bumping the spec to 0.5.0.

**Architecture:** A neutral `forgelab/formats/fcstd.py` codec reads/writes a canonical subset of the FCStd ZIP + `Document.xml` (flat, ordered objects with typed properties), used by both a real `FreeCADImporter` and `FreeCADExporter` (which never depend on each other). Typed Pydantic models in `forgelab/spec/mechanical.py` serialize into the generic `Node` graph as flat document-order nodes whose `props` carry link references for assembly/feature relationships.

**Tech Stack:** Python 3.11+, Pydantic v2, stdlib `zipfile` + `xml.etree.ElementTree`, pytest. Run tooling with the venv on PATH: `PATH="$PWD/.venv/bin:$PATH" <cmd>` (ruff, pyright, pytest).

---

## Notes for the implementer

- Run every tool with `PATH="$PWD/.venv/bin:$PATH"` prefixed (ruff, ruff format, pyright, pytest).
- **Module boundary rule (load-bearing):** `forgelab/importers/mechanical/` and `forgelab/exporters/mechanical/` may import only from `forgelab.spec` (incl. `forgelab.spec.mechanical`) and `forgelab.formats` — never from each other, never from `forgelab.core`.
- **Name-collision rule:** `forgelab.spec` already exports a hardware `Pad`. The mechanical models (including a mechanical `Pad`) must **NOT** be re-exported from `forgelab/spec/__init__.py` — that would shadow the hardware `Pad` and break KiCad. All consumers import mechanical models from the submodule `forgelab.spec.mechanical`.
- **Determinism levers:** preserve document order; format floats with `repr(float(x))` so a re-read is exact; write the ZIP with a fixed `date_time` so output is byte-stable.
- `claude-opus-4-8` etc. are not relevant here; this is offline CAD work. No network in any test. No FreeCAD installed.

---

### Task 1: Mechanical spec models + version bump to 0.5.0

**Files:**
- Create: `forgelab/spec/mechanical.py`
- Modify: `forgelab/spec/version.py`
- Test: `tests/test_spec_mechanical.py`, `tests/test_spec.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_spec_mechanical.py`:

```python
import pytest
from pydantic import ValidationError

from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SKETCH,
    Body,
    Constraint,
    Pad,
    Placement,
    Pocket,
    Part,
    Sketch,
    SketchGeometry,
)


def test_node_type_constants():
    assert (NODE_PART, NODE_BODY, NODE_SKETCH, NODE_PAD, NODE_POCKET) == (
        "part",
        "body",
        "sketch",
        "pad",
        "pocket",
    )


def test_placement_defaults_to_identity():
    p = Placement()
    assert p.position == [0.0, 0.0, 0.0]
    assert p.rotation == [0.0, 0.0, 0.0, 1.0]


def test_placement_validates_lengths():
    with pytest.raises(ValidationError):
        Placement(position=[0.0, 0.0])
    with pytest.raises(ValidationError):
        Placement(rotation=[0.0, 0.0, 0.0])


def test_line_geometry_requires_four_points():
    line = SketchGeometry(geo_type="line", points=[0.0, 0.0, 40.0, 0.0])
    assert line.points == [0.0, 0.0, 40.0, 0.0]
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="line", points=[0.0, 0.0])


def test_circle_geometry_requires_center():
    circle = SketchGeometry(geo_type="circle", center=[20.0, 10.0], radius=4.0)
    assert circle.radius == 4.0
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="circle", center=[20.0])


def test_unknown_geo_type_rejected():
    with pytest.raises(ValidationError):
        SketchGeometry(geo_type="spline", points=[0.0, 0.0, 1.0, 1.0])


def test_models_forbid_extra_fields():
    with pytest.raises(ValidationError):
        Pad(name="Pad", length=10.0, bogus=1)


def test_sketch_holds_geometry_and_constraints():
    sketch = Sketch(
        name="Sketch",
        body="Body",
        geometry=[SketchGeometry(geo_type="circle", center=[0.0, 0.0], radius=2.0)],
        constraints=[Constraint(ctype="Radius", value=2.0, name="r")],
    )
    assert sketch.plane == "XY_Plane"
    assert sketch.constraints[0].value == 2.0


def test_pad_and_pocket_links_and_flags():
    pad = Pad(name="Pad", body="Body", profile="Sketch", length=10.0)
    assert pad.reversed is False and pad.midplane is False
    pocket = Pocket(name="Pocket", body="Body", profile="Sketch001", through_all=True)
    assert pocket.through_all is True
    part = Part(name="Part")
    body = Body(name="Body", part="Part")
    assert body.part == "Part" and part.name == "Part"
```

In `tests/test_spec.py`, replace the version assertion (currently asserts `"0.4.0"`) with:

```python
def test_spec_version_is_0_5_0():
    from forgelab.spec.version import SPEC_VERSION

    assert SPEC_VERSION == "0.5.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_spec_mechanical.py tests/test_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: forgelab.spec.mechanical` and version mismatch.

- [ ] **Step 3: Create `forgelab/spec/mechanical.py`**

```python
"""Typed mechanical-CAD (FreeCAD) vocabulary for the ForgeLab IR.

These models describe FreeCAD PartDesign concepts — parts, bodies, sketches,
and parametric features (pad/extrusion, pocket/cut) — plus the sketch geometry
and dimensional constraints that drive them. Like the hardware and 3D
vocabularies they are not a new document root: they serialize into the generic
``Node`` graph. The object graph is flat and document-ordered; assembly and
feature relationships are expressed as link references stored in ``props``
(e.g. ``body.part``, ``pad.profile``).

NOTE: these models are imported from this submodule (``forgelab.spec.mechanical``),
not re-exported from ``forgelab.spec``, because ``Pad`` would collide with the
hardware ``Pad`` already exported there.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NODE_PART = "part"
NODE_BODY = "body"
NODE_SKETCH = "sketch"
NODE_PAD = "pad"
NODE_POCKET = "pocket"


class Placement(BaseModel):
    """A rigid placement: translation + rotation quaternion [x, y, z, w]."""

    model_config = ConfigDict(extra="forbid")

    position: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])

    @field_validator("position")
    @classmethod
    def _position_is_vec3(cls, value: list[float]) -> list[float]:
        if len(value) != 3:
            raise ValueError("position must be [x, y, z]")
        return value

    @field_validator("rotation")
    @classmethod
    def _rotation_is_quat(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("rotation must be a quaternion [x, y, z, w]")
        return value


class Part(BaseModel):
    """An assembly container (App::Part)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    placement: Placement = Field(default_factory=Placement)


class Body(BaseModel):
    """A solid body (PartDesign::Body), optionally inside a Part."""

    model_config = ConfigDict(extra="forbid")

    name: str
    part: str = ""
    placement: Placement = Field(default_factory=Placement)


class SketchGeometry(BaseModel):
    """One geometry primitive in a sketch: a line segment or a circle."""

    model_config = ConfigDict(extra="forbid")

    geo_type: str
    points: list[float] = Field(default_factory=list)
    center: list[float] = Field(default_factory=list)
    radius: float = 0.0

    @field_validator("geo_type")
    @classmethod
    def _known_geo_type(cls, value: str) -> str:
        if value not in ("line", "circle"):
            raise ValueError("geo_type must be 'line' or 'circle'")
        return value

    @model_validator(mode="after")
    def _check_shape(self) -> "SketchGeometry":
        if self.geo_type == "line":
            if len(self.points) != 4:
                raise ValueError("line geometry needs points [x1, y1, x2, y2]")
            if self.center or self.radius:
                raise ValueError("line geometry must not set center/radius")
        else:  # circle
            if len(self.center) != 2:
                raise ValueError("circle geometry needs center [x, y]")
            if self.points:
                raise ValueError("circle geometry must not set points")
        return self


class Constraint(BaseModel):
    """A dimensional constraint (a sketch dimension)."""

    model_config = ConfigDict(extra="forbid")

    ctype: str
    value: float
    name: str = ""


class Sketch(BaseModel):
    """A sketch: geometry primitives + dimensional constraints on a plane."""

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    plane: str = "XY_Plane"
    placement: Placement = Field(default_factory=Placement)
    geometry: list[SketchGeometry] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)


class Pad(BaseModel):
    """A pad feature: extrude a sketch profile by a length (PartDesign::Pad)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    profile: str = ""
    length: float
    reversed: bool = False
    midplane: bool = False


class Pocket(BaseModel):
    """A pocket feature: cut a sketch profile into a body (PartDesign::Pocket)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    body: str = ""
    profile: str = ""
    length: float = 0.0
    through_all: bool = False
    reversed: bool = False
    midplane: bool = False
```

- [ ] **Step 4: Bump the spec version**

In `forgelab/spec/version.py`, set:

```python
SPEC_VERSION = "0.5.0"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_spec_mechanical.py tests/test_spec.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite + lint + types**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest -q && PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" ruff format --check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/spec/mechanical.py`
Expected: all pass. (Existing examples are spec 0.4.0 but remain major-compatible, so `test_examples.py` still passes.)

- [ ] **Step 7: Commit**

```bash
git add forgelab/spec/mechanical.py forgelab/spec/version.py tests/test_spec_mechanical.py tests/test_spec.py
git commit -m "feat(spec): mechanical vocabulary (Part/Body/Sketch/Pad/Pocket), bump to 0.5.0"
```

---

### Task 2: FCStd codec — `forgelab/formats/fcstd.py`

**Files:**
- Create: `forgelab/formats/fcstd.py`
- Modify: `forgelab/formats/__init__.py`
- Test: `tests/test_fcstd_codec.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fcstd_codec.py`:

```python
import zipfile
from io import BytesIO

import pytest

from forgelab.formats import (
    FcDocument,
    FcObject,
    FcProperty,
    FcstdError,
    read_document,
    read_objects,
    write_fcstd,
)


def _sample_document():
    return FcDocument(
        name="doc",
        generator="forgelab-freecad",
        objects=[
            FcObject(
                name="Pad",
                obj_type="PartDesign::Pad",
                properties=[
                    FcProperty("name", "String", "Pad"),
                    FcProperty("profile", "Link", "Sketch"),
                    FcProperty("length", "Float", 10.0),
                    FcProperty("reversed", "Bool", False),
                ],
            ),
            FcObject(
                name="Body",
                obj_type="PartDesign::Body",
                properties=[
                    FcProperty(
                        "placement",
                        "Placement",
                        {"position": [1.0, 2.0, 3.0], "rotation": [0.0, 0.0, 0.0, 1.0]},
                    ),
                ],
            ),
            FcObject(
                name="Sketch",
                obj_type="Sketcher::SketchObject",
                properties=[
                    FcProperty(
                        "geometry",
                        "GeometryList",
                        [
                            {"geo_type": "line", "points": [0.0, 0.0, 40.0, 0.0], "center": [], "radius": 0.0},
                            {"geo_type": "circle", "points": [], "center": [20.0, 10.0], "radius": 4.0},
                        ],
                    ),
                    FcProperty(
                        "constraints",
                        "ConstraintList",
                        [{"ctype": "DistanceX", "value": 40.0, "name": "w"}],
                    ),
                ],
            ),
        ],
    )


def test_roundtrip_preserves_everything():
    doc = _sample_document()
    restored = read_document(write_fcstd(doc))
    assert restored == doc


def test_read_objects_is_objects_only():
    doc = _sample_document()
    objs = read_objects(write_fcstd(doc))
    assert [o.name for o in objs] == ["Pad", "Body", "Sketch"]


def test_output_is_a_zip_with_document_xml():
    data = write_fcstd(_sample_document())
    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert "Document.xml" in zf.namelist()


def test_write_is_byte_stable():
    doc = _sample_document()
    assert write_fcstd(doc) == write_fcstd(doc)


def test_not_a_zip_raises():
    with pytest.raises(FcstdError):
        read_document(b"not a zip")


def test_missing_document_xml_raises():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Other.xml", "<x/>")
    with pytest.raises(FcstdError):
        read_document(buffer.getvalue())


def test_malformed_xml_raises():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Document.xml", "<Document><not closed>")
    with pytest.raises(FcstdError):
        read_document(buffer.getvalue())


def test_unsupported_property_type_raises_on_write():
    doc = FcDocument(objects=[FcObject("X", "App::Part", [FcProperty("p", "Mystery", 1)])])
    with pytest.raises(FcstdError):
        write_fcstd(doc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_fcstd_codec.py -v`
Expected: FAIL — import errors (module/symbols missing).

- [ ] **Step 3: Create `forgelab/formats/fcstd.py`**

```python
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
        for key, val in zip(
            ("px", "py", "pz", "qx", "qy", "qz", "qw"), (*pos, *rot)
        ):
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
```

- [ ] **Step 4: Re-export from `forgelab/formats/__init__.py`**

Add the FCStd imports and extend `__all__`:

```python
from forgelab.formats.fcstd import (
    FcDocument,
    FcObject,
    FcProperty,
    FcstdError,
    read_document,
    read_objects,
    write_fcstd,
)
```

Append to `__all__`: `"FcDocument"`, `"FcObject"`, `"FcProperty"`, `"FcstdError"`, `"read_document"`, `"read_objects"`, `"write_fcstd"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_fcstd_codec.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Full gate**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest -q && PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" ruff format --check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/formats/fcstd.py`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add forgelab/formats/fcstd.py forgelab/formats/__init__.py tests/test_fcstd_codec.py
git commit -m "feat(formats): FCStd codec (zip + Document.xml, deterministic)"
```

---

### Task 3: FreeCAD importer package

**Files:**
- Delete: `forgelab/importers/mechanical.py`
- Create: `forgelab/importers/mechanical/__init__.py`, `forgelab/importers/mechanical/native.py`, `forgelab/importers/mechanical/freecad.py`
- Test: `tests/test_freecad_importer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_freecad_importer.py`:

```python
import pytest

from forgelab.formats import FcDocument, FcObject, FcProperty, write_fcstd
from forgelab.importers.mechanical import FreeCADImporter, FreeCADParseError


def _box_fcstd():
    objects = [
        FcObject("Part", "App::Part", [FcProperty("name", "String", "Part")]),
        FcObject(
            "Body",
            "PartDesign::Body",
            [FcProperty("name", "String", "Body"), FcProperty("part", "Link", "Part")],
        ),
        FcObject(
            "Pad",
            "PartDesign::Pad",
            [
                FcProperty("name", "String", "Pad"),
                FcProperty("body", "Link", "Body"),
                FcProperty("profile", "Link", "Sketch"),
                FcProperty("length", "Float", 10.0),
            ],
        ),
    ]
    return write_fcstd(FcDocument(objects=objects, name="box", generator="forgelab-freecad"))


def test_import_maps_objects_to_nodes_in_order():
    doc = FreeCADImporter().to_ir(_box_fcstd())
    assert doc.domain.value == "mechanical"
    assert [(n.id, n.type) for n in doc.nodes] == [
        ("Part", "part"),
        ("Body", "body"),
        ("Pad", "pad"),
    ]
    assert doc.meta.name == "box"


def test_import_preserves_link_props_and_values():
    doc = FreeCADImporter().to_ir(_box_fcstd())
    pad = next(n for n in doc.nodes if n.id == "Pad")
    assert pad.props["body"] == "Body"
    assert pad.props["profile"] == "Sketch"
    assert pad.props["length"] == 10.0


def test_unknown_object_type_raises():
    bad = write_fcstd(FcDocument(objects=[FcObject("X", "App::Mystery", [])]))
    with pytest.raises(FreeCADParseError):
        FreeCADImporter().to_ir(bad)


def test_not_a_zip_raises_parse_error():
    with pytest.raises(FreeCADParseError):
        FreeCADImporter().to_ir(b"garbage")


def test_invalid_props_raise_parse_error():
    # Pad requires a `length`; omit it.
    bad = write_fcstd(
        FcDocument(objects=[FcObject("Pad", "PartDesign::Pad", [FcProperty("name", "String", "Pad")])])
    )
    with pytest.raises(FreeCADParseError):
        FreeCADImporter().to_ir(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_freecad_importer.py -v`
Expected: FAIL — `ImportError: cannot import name 'FreeCADParseError'` (still the stub module).

- [ ] **Step 3: Convert the stub module into a package**

```bash
git rm forgelab/importers/mechanical.py
mkdir -p forgelab/importers/mechanical
```

Create `forgelab/importers/mechanical/native.py`:

```python
"""Mechanical-CAD native-format importers (Fusion 360). (stub)"""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class Fusion360Importer(Importer):
    """Import a Fusion 360 model into ForgeLab IR. (stub)"""

    tool_name = "fusion360"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Fusion 360 import is not implemented yet.")
```

Create `forgelab/importers/mechanical/freecad.py`:

```python
"""FreeCAD .FCStd importer -> ForgeLab IR."""

from forgelab.formats import FcstdError, read_document
from forgelab.importers.base import Importer
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SKETCH,
    Body,
    Pad,
    Part,
    Pocket,
    Sketch,
)
from forgelab.spec.version import SPEC_VERSION

_NODE_BY_FCTYPE = {
    "App::Part": NODE_PART,
    "PartDesign::Body": NODE_BODY,
    "Sketcher::SketchObject": NODE_SKETCH,
    "PartDesign::Pad": NODE_PAD,
    "PartDesign::Pocket": NODE_POCKET,
}

_MODEL_BY_NODE = {
    NODE_PART: Part,
    NODE_BODY: Body,
    NODE_SKETCH: Sketch,
    NODE_PAD: Pad,
    NODE_POCKET: Pocket,
}


class FreeCADParseError(FcstdError):
    """Raised when an FCStd document cannot be mapped to ForgeLab IR."""


class FreeCADImporter(Importer):
    """Import a FreeCAD .FCStd model into ForgeLab IR."""

    tool_name = "freecad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        try:
            fc_doc = read_document(source)
        except FcstdError as exc:
            raise FreeCADParseError(str(exc)) from exc

        nodes: list[Node] = []
        for obj in fc_doc.objects:
            node_type = _NODE_BY_FCTYPE.get(obj.obj_type)
            if node_type is None:
                raise FreeCADParseError(
                    f"Unknown FreeCAD object type {obj.obj_type!r} on object {obj.name!r}"
                )
            props = {prop.name: prop.value for prop in obj.properties}
            model = _MODEL_BY_NODE[node_type]
            try:
                validated = model.model_validate(props)
            except Exception as exc:
                raise FreeCADParseError(
                    f"Object {obj.name!r} has invalid {node_type} properties: {exc}"
                ) from exc
            nodes.append(Node(id=obj.name, type=node_type, props=validated.model_dump()))

        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.MECHANICAL,
            meta=DocumentMeta(
                name=fc_doc.name or "freecad-document",
                generator=fc_doc.generator or "forgelab-freecad",
            ),
            nodes=nodes,
        )
```

Create `forgelab/importers/mechanical/__init__.py`:

```python
"""Mechanical-CAD importers (FreeCAD real; Fusion 360 native stub) -> ForgeLab IR."""

from forgelab.importers.mechanical.freecad import FreeCADImporter, FreeCADParseError
from forgelab.importers.mechanical.native import Fusion360Importer

__all__ = ["FreeCADImporter", "FreeCADParseError", "Fusion360Importer"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_freecad_importer.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Boundary + full gate**

Run: `grep -rnE "import .*(exporters|forgelab\.core)" forgelab/importers/mechanical/` — must be empty.
Run: `PATH="$PWD/.venv/bin:$PATH" pytest -q && PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" ruff format --check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" pyright`
Expected: all pass (pyright 0 errors); `test_stubs.py` still passes (it imports `FreeCADImporter` from the package and checks `tool_name == "freecad"`).

- [ ] **Step 6: Commit**

```bash
git add forgelab/importers/mechanical tests/test_freecad_importer.py
git commit -m "feat(importers): real FreeCAD .FCStd importer (mechanical package)"
```

---

### Task 4: FreeCAD exporter package

**Files:**
- Delete: `forgelab/exporters/mechanical.py`
- Create: `forgelab/exporters/mechanical/__init__.py`, `forgelab/exporters/mechanical/native.py`, `forgelab/exporters/mechanical/freecad.py`
- Test: `tests/test_freecad_exporter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_freecad_exporter.py`:

```python
import pytest

from forgelab.exporters.mechanical import FreeCADExporter
from forgelab.formats import read_document
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.spec.mechanical import Body, Pad, Part


def _doc():
    part = Part(name="Part")
    body = Body(name="Body", part="Part")
    pad = Pad(name="Pad", body="Body", profile="Sketch", length=10.0)
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="box", generator="forgelab-freecad"),
        nodes=[
            Node(id="Part", type="part", props=part.model_dump()),
            Node(id="Body", type="body", props=body.model_dump()),
            Node(id="Pad", type="pad", props=pad.model_dump()),
        ],
    )


def test_export_produces_readable_fcstd():
    data = FreeCADExporter().from_ir(_doc())
    fc_doc = read_document(data)
    assert fc_doc.name == "box"
    assert [(o.name, o.obj_type) for o in fc_doc.objects] == [
        ("Part", "App::Part"),
        ("Body", "PartDesign::Body"),
        ("Pad", "PartDesign::Pad"),
    ]


def test_exported_pad_carries_length_and_links():
    data = FreeCADExporter().from_ir(_doc())
    fc_doc = read_document(data)
    pad = next(o for o in fc_doc.objects if o.name == "Pad")
    by_name = {p.name: p for p in pad.properties}
    assert by_name["length"].value == 10.0
    assert by_name["profile"].value == "Sketch"
    assert by_name["profile"].ptype == "Link"


def test_export_is_byte_stable():
    doc = _doc()
    assert FreeCADExporter().from_ir(doc) == FreeCADExporter().from_ir(doc)


def test_unknown_node_type_raises():
    doc = ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="x"),
        nodes=[Node(id="weird", type="wormhole", props={})],
    )
    with pytest.raises(ValueError):
        FreeCADExporter().from_ir(doc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_freecad_exporter.py -v`
Expected: FAIL — still the stub module (`from_ir` raises NotImplementedError / no real mapping).

- [ ] **Step 3: Convert the stub module into a package**

```bash
git rm forgelab/exporters/mechanical.py
mkdir -p forgelab/exporters/mechanical
```

Create `forgelab/exporters/mechanical/native.py`:

```python
"""Mechanical-CAD native-format exporters (Fusion 360). (stub)"""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class Fusion360Exporter(Exporter):
    """Export ForgeLab IR to a Fusion 360 model. (stub)"""

    tool_name = "fusion360"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Fusion 360 export is not implemented yet.")
```

Create `forgelab/exporters/mechanical/freecad.py`:

```python
"""FreeCAD .FCStd exporter from ForgeLab IR."""

from forgelab.exporters.base import Exporter
from forgelab.formats import FcDocument, FcObject, FcProperty, write_fcstd
from forgelab.spec import ForgeDocument
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SKETCH,
)

_FCTYPE_BY_NODE = {
    NODE_PART: "App::Part",
    NODE_BODY: "PartDesign::Body",
    NODE_SKETCH: "Sketcher::SketchObject",
    NODE_PAD: "PartDesign::Pad",
    NODE_POCKET: "PartDesign::Pocket",
}

# field name -> property type, per node type, in canonical write order.
_FIELDS = {
    NODE_PART: [("name", "String"), ("placement", "Placement")],
    NODE_BODY: [("name", "String"), ("part", "Link"), ("placement", "Placement")],
    NODE_SKETCH: [
        ("name", "String"),
        ("body", "Link"),
        ("plane", "String"),
        ("placement", "Placement"),
        ("geometry", "GeometryList"),
        ("constraints", "ConstraintList"),
    ],
    NODE_PAD: [
        ("name", "String"),
        ("body", "Link"),
        ("profile", "Link"),
        ("length", "Float"),
        ("reversed", "Bool"),
        ("midplane", "Bool"),
    ],
    NODE_POCKET: [
        ("name", "String"),
        ("body", "Link"),
        ("profile", "Link"),
        ("length", "Float"),
        ("through_all", "Bool"),
        ("reversed", "Bool"),
        ("midplane", "Bool"),
    ],
}


class FreeCADExporter(Exporter):
    """Export ForgeLab mechanical IR to a FreeCAD .FCStd file."""

    tool_name = "freecad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        objects: list[FcObject] = []
        for node in document.nodes:
            fc_type = _FCTYPE_BY_NODE.get(node.type)
            if fc_type is None:
                raise ValueError(f"Cannot export node type {node.type!r} to FreeCAD")
            properties = [
                FcProperty(name=field_name, ptype=ptype, value=node.props[field_name])
                for field_name, ptype in _FIELDS[node.type]
            ]
            objects.append(
                FcObject(name=node.id, obj_type=fc_type, properties=properties)
            )
        fc_doc = FcDocument(
            objects=objects,
            name=document.meta.name,
            generator=document.meta.generator or "forgelab-freecad",
        )
        return write_fcstd(fc_doc)
```

Create `forgelab/exporters/mechanical/__init__.py`:

```python
"""Mechanical-CAD exporters (FreeCAD real; Fusion 360 native stub) from ForgeLab IR."""

from forgelab.exporters.mechanical.freecad import FreeCADExporter
from forgelab.exporters.mechanical.native import Fusion360Exporter

__all__ = ["FreeCADExporter", "Fusion360Exporter"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_freecad_exporter.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Boundary + full gate**

Run: `grep -rnE "import .*(importers|forgelab\.core)" forgelab/exporters/mechanical/` — must be empty.
Run: `PATH="$PWD/.venv/bin:$PATH" pytest -q && PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" ruff format --check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" pyright`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add forgelab/exporters/mechanical tests/test_freecad_exporter.py
git commit -m "feat(exporters): real FreeCAD .FCStd exporter (mechanical package)"
```

---

### Task 5: Round-trip guarantee + box-with-hole example

**Files:**
- Create: `examples/mechanical/box-with-hole.FCStd`, `examples/mechanical/box-with-hole.forge.json`
- Test: `tests/test_freecad_roundtrip.py`

- [ ] **Step 1: Write the failing round-trip test**

Create `tests/test_freecad_roundtrip.py`:

```python
from pathlib import Path

from forgelab.exporters.mechanical import FreeCADExporter
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.spec import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.spec.mechanical import (
    Body,
    Constraint,
    Pad,
    Pocket,
    Part,
    Sketch,
    SketchGeometry,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "mechanical"


def _box_with_hole_doc():
    part = Part(name="Part")
    body = Body(name="Body", part="Part")
    base = Sketch(
        name="Sketch",
        body="Body",
        plane="XY_Plane",
        geometry=[
            SketchGeometry(geo_type="line", points=[0.0, 0.0, 40.0, 0.0]),
            SketchGeometry(geo_type="line", points=[40.0, 0.0, 40.0, 20.0]),
            SketchGeometry(geo_type="line", points=[40.0, 20.0, 0.0, 20.0]),
            SketchGeometry(geo_type="line", points=[0.0, 20.0, 0.0, 0.0]),
        ],
        constraints=[
            Constraint(ctype="DistanceX", value=40.0, name="Width"),
            Constraint(ctype="DistanceY", value=20.0, name="Depth"),
        ],
    )
    pad = Pad(name="Pad", body="Body", profile="Sketch", length=10.0)
    hole_sketch = Sketch(
        name="Sketch001",
        body="Body",
        plane="XY_Plane",
        geometry=[SketchGeometry(geo_type="circle", center=[20.0, 10.0], radius=4.0)],
        constraints=[Constraint(ctype="Radius", value=4.0, name="HoleRadius")],
    )
    pocket = Pocket(name="Pocket", body="Body", profile="Sketch001", through_all=True)
    pairs = [
        (part, "part"),
        (body, "body"),
        (base, "sketch"),
        (pad, "pad"),
        (hole_sketch, "sketch"),
        (pocket, "pocket"),
    ]
    return ForgeDocument(
        forgelab_version="0.5.0",
        domain=Domain.MECHANICAL,
        meta=DocumentMeta(name="box-with-hole", generator="forgelab-freecad"),
        nodes=[Node(id=m.name, type=t, props=m.model_dump()) for m, t in pairs],
    )


def test_roundtrip_is_identity():
    doc = _box_with_hole_doc()
    data = FreeCADExporter().from_ir(doc)
    assert FreeCADImporter().to_ir(data) == doc


def test_roundtrip_is_stable_twice():
    doc = _box_with_hole_doc()
    once = FreeCADExporter().from_ir(doc)
    twice = FreeCADExporter().from_ir(FreeCADImporter().to_ir(once))
    assert once == twice


def test_example_files_match_generated():
    doc = _box_with_hole_doc()
    fcstd_bytes = (EXAMPLES / "box-with-hole.FCStd").read_bytes()
    assert FreeCADImporter().to_ir(fcstd_bytes) == doc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_freecad_roundtrip.py -v`
Expected: the round-trip identity/stability tests PASS, but `test_example_files_match_generated` FAILS (example files don't exist yet).

- [ ] **Step 3: Generate the example files**

```bash
mkdir -p examples/mechanical
PATH="$PWD/.venv/bin:$PATH" python -c "
from pathlib import Path
import sys
sys.path.insert(0, 'tests')
from test_freecad_roundtrip import _box_with_hole_doc
from forgelab.exporters.mechanical import FreeCADExporter
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.sdk import dump

doc = _box_with_hole_doc()
fcstd = FreeCADExporter().from_ir(doc)
Path('examples/mechanical/box-with-hole.FCStd').write_bytes(fcstd)
imported = FreeCADImporter().to_ir(fcstd)
assert imported == doc, 'round-trip mismatch while generating example'
Path('examples/mechanical/box-with-hole.forge.json').write_text(dump(imported) + '\n')
print('generated example; forgelab_version:', imported.forgelab_version)
"
```

Expected output includes `forgelab_version: 0.5.0`.

- [ ] **Step 4: Regenerate the existing examples at 0.5.0 (freshness)**

```bash
PATH="$PWD/.venv/bin:$PATH" python -c "
from pathlib import Path
from forgelab.importers.hardware.kicad import KiCadImporter
from forgelab.importers.threed.gltf import GltfImporter
from forgelab.sdk import dump

hw = KiCadImporter().to_ir(Path('examples/hardware/blinky.kicad_pcb').read_bytes())
Path('examples/hardware/blinky.forge.json').write_text(dump(hw) + '\n')
td = GltfImporter().to_ir(Path('examples/threed/cube.gltf').read_bytes())
Path('examples/threed/cube.forge.json').write_text(dump(td) + '\n')
print('regenerated hardware + 3D examples at 0.5.0')
"
grep -l '"forgelab_version": "0.5.0"' examples/hardware/blinky.forge.json examples/threed/cube.forge.json examples/mechanical/box-with-hole.forge.json
```

Expected: all three files listed.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_freecad_roundtrip.py tests/test_examples.py -v`
Expected: PASS (3 round-trip tests + examples validate).

- [ ] **Step 6: Full gate**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest -q && PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" ruff format --check forgelab/ tests/`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tests/test_freecad_roundtrip.py examples/mechanical examples/hardware/blinky.forge.json examples/threed/cube.forge.json
git commit -m "feat(mechanical): FreeCAD round-trip guarantee + box-with-hole example, regen examples at 0.5.0"
```

---

### Task 6: Wire the mechanical domain into the AI SDK

**Files:**
- Modify: `forgelab/sdk/schema.py`, `forgelab/sdk/prompts.py`
- Test: `tests/test_sdk_schema.py`, `tests/test_sdk_prompts.py`

- [ ] **Step 1: Update the failing tests**

In `tests/test_sdk_schema.py`, replace `test_registry_covers_both_domains` with:

```python
def test_registry_covers_all_domains():
    assert set(DOMAIN_VOCAB) == {"hardware", "threed", "mechanical"}
    assert set(DOMAIN_VOCAB["hardware"]) == {"board", "net", "component"}
    assert set(DOMAIN_VOCAB["threed"]) == {"scene", "material", "mesh", "object"}
    assert set(DOMAIN_VOCAB["mechanical"]) == {"part", "body", "sketch", "pad", "pocket"}


def test_mechanical_schema_pins_domain_and_includes_pad():
    schema = domain_schema("mechanical")
    assert schema["properties"]["domain"] == {"const": "mechanical"}
    consts = {v["properties"]["type"]["const"] for v in _variants(schema)}
    assert consts == {"part", "body", "sketch", "pad", "pocket"}
```

In `tests/test_sdk_prompts.py`, change every `@pytest.mark.parametrize("domain", [...])` decorator that lists domains to include `"mechanical"`:

```python
@pytest.mark.parametrize("domain", ["hardware", "threed", "mechanical"])
```

(Apply to both parametrized tests — `test_system_prompt_nonempty_and_names_domain` and `test_few_shot_examples_are_valid`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_sdk_schema.py tests/test_sdk_prompts.py -v`
Expected: FAIL — `"mechanical"` not in `DOMAIN_VOCAB`; `few_shot("mechanical")` raises `KeyError`.

- [ ] **Step 3: Register mechanical in the schema registry**

In `forgelab/sdk/schema.py`, add this import block (after the existing `from forgelab.spec import (...)` block):

```python
from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SKETCH,
    Body,
    Pad,
    Part,
    Pocket,
    Sketch,
)
```

Then add a `"mechanical"` entry to `DOMAIN_VOCAB`:

```python
    "mechanical": {
        NODE_PART: Part,
        NODE_BODY: Body,
        NODE_SKETCH: Sketch,
        NODE_PAD: Pad,
        NODE_POCKET: Pocket,
    },
```

(`SketchGeometry`, `Constraint`, and `Placement` are nested sub-models, not node
types — `domain_schema` hoists their `$defs` automatically and
`validate_llm_output` validates them through their parent models, so they need no
registry entry.)

- [ ] **Step 4: Add the mechanical few-shot example**

In `forgelab/sdk/prompts.py`, add to the `_FEW_SHOT` dict:

```python
    "mechanical": (
        "a 40x20x10 box with a through hole",
        "mechanical/box-with-hole.forge.json",
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_sdk_schema.py tests/test_sdk_prompts.py -v`
Expected: PASS (the mechanical few-shot example round-trips through `validate_llm_output`, and `domain_schema("mechanical")` resolves all `$ref`s including nested `Placement`/`SketchGeometry`/`Constraint`).

- [ ] **Step 6: Full gate**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest -q && PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" ruff format --check forgelab/ tests/ && PATH="$PWD/.venv/bin:$PATH" pyright`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add forgelab/sdk/schema.py forgelab/sdk/prompts.py tests/test_sdk_schema.py tests/test_sdk_prompts.py
git commit -m "feat(sdk): register mechanical domain (schema + few-shot)"
```

---

### Task 7: Documentation — README + CHANGELOG

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Update the spec badge**

In `README.md`, change the spec badge from `spec-v0.4.0` to:

```markdown
[![Spec](https://img.shields.io/badge/spec-v0.5.0-orange.svg)](forgelab/spec/version.py)
```

- [ ] **Step 2: Update the tool-support table**

In the Mechanical CAD rows of the tool-support table, set FreeCAD to implemented and keep Fusion 360 as a stub:

```markdown
| Mechanical CAD | FreeCAD       |   ✅   |   ✅   | `.FCStd` round-trip (parts/bodies/features/sketch dimensions) |
| Mechanical CAD | Fusion 360    |   🚧   |   🚧   | stub                                         |
```

(If the existing FreeCAD/Fusion 360 rows differ in wording, edit them in place to the above; do not duplicate rows.)

- [ ] **Step 3: Add a quickstart subsection + TOC entry**

In the Table of Contents, add under Quickstart (after the glTF entry):

```markdown
  - [Round-trip a FreeCAD model](#round-trip-a-freecad-model)
```

In the Quickstart section, after the glTF subsection, add:

````markdown
### Round-trip a FreeCAD model

Import a FreeCAD `.FCStd` mechanical model, work with the feature tree as JSON,
and export it back:

```python
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.exporters.mechanical import FreeCADExporter

source = open("examples/mechanical/box-with-hole.FCStd", "rb").read()

doc = FreeCADImporter().to_ir(source)         # .FCStd -> ForgeDocument
features = [n.id for n in doc.nodes if n.type in ("pad", "pocket")]
print(features)                               # ['Pad', 'Pocket']

fcstd_bytes = FreeCADExporter().from_ir(doc)  # ForgeDocument -> .FCStd

# The round-trip is stable: import -> export -> import is an identity over the IR.
assert FreeCADImporter().to_ir(fcstd_bytes) == doc
```

The parametric feature tree — parts, bodies, sketches with dimensions, pads
(extrusions) and pockets (cuts) — is captured as plain JSON nodes with link
references, so an agent can read and edit the model directly. Parsing uses only
the standard library (`zipfile` + `xml.etree`), so **no FreeCAD installation is
required**.
````

- [ ] **Step 4: Update Project status + Spec versioning + Roadmap**

- In "Project status": update the spec version to v0.5.0 and state there are now
  **three** end-to-end round-trips (KiCad hardware, glTF 3D, FreeCAD mechanical).
- In "Spec versioning": change the current spec version to **v0.5.0**.
- In the Roadmap: check the Mechanical CAD / FreeCAD item (`- [x]`), and update
  remaining mechanical references (Fusion 360 stays unchecked).

- [ ] **Step 5: Update the repository-layout note**

In the `formats/` line of the repository-layout block, mention the FCStd codec, e.g.:

```
├── formats/     # shared, zero-dependency format primitives (S-expression, glTF, FCStd)
```

- [ ] **Step 6: Add a CHANGELOG entry**

In `CHANGELOG.md`, under `## [Unreleased]`, fold into the existing `### Added` / `### Changed` sections (match the file's style):

```markdown
### Added
- Mechanical CAD domain: typed vocabulary (`forgelab/spec/mechanical.py` —
  Part/Body/Sketch/SketchGeometry/Constraint/Pad/Pocket/Placement), a stdlib-only
  FCStd codec (`forgelab/formats/fcstd.py`), real FreeCAD `.FCStd`
  importer/exporter with an IR-level round-trip guarantee, and a box-with-hole
  example.
- Mechanical domain registered in the AI SDK (`domain_schema`/`system_prompt`/
  `few_shot`/`validate_llm_output` now support `"mechanical"`).

### Changed
- `SPEC_VERSION` bumped to 0.5.0; example `.forge.json` files regenerated.
- `forgelab.importers.mechanical` and `forgelab.exporters.mechanical` are now
  packages (FreeCAD implemented; Fusion 360 native stubs preserved).
```

- [ ] **Step 7: Verify and commit**

Run: `grep -n "0.4.0\|0.3.0\|0.2.0" README.md` — expect no stale spec-version references (only 0.5.0). Fix any stragglers.
Run: `PATH="$PWD/.venv/bin:$PATH" pytest -q` (docs don't affect tests; confirm still green).

```bash
git add README.md CHANGELOG.md
git commit -m "docs: FreeCAD mechanical quickstart, spec 0.5.0 badge/status, CHANGELOG"
```

---

## Final verification (after all tasks)

- [ ] Full quality gate:

```bash
PATH="$PWD/.venv/bin:$PATH" ruff check . && \
PATH="$PWD/.venv/bin:$PATH" ruff format --check . && \
PATH="$PWD/.venv/bin:$PATH" pyright && \
PATH="$PWD/.venv/bin:$PATH" pytest -q
```

Expected: ruff clean, format clean, pyright 0 errors, all tests pass.

- [ ] Boundary check: `grep -rnE "import .*(importers|exporters)" forgelab/formats/ forgelab/spec/` returns nothing; mechanical importer doesn't import exporters/core and vice-versa.
- [ ] Pipeline sanity: `PATH="$PWD/.venv/bin:$PATH" python -c "from forgelab.core import default_registry; r = default_registry(); print('freecad' in r.exporters)"` (or equivalent) — FreeCAD is registered and real.

---

## Self-review notes

- **Spec coverage:** format=FCStd via stdlib (Tasks 2–4) ✓; models Part/Body/Sketch/SketchGeometry/Constraint/Pad/Pocket/Placement (Task 1) ✓; flat nodes + link refs (Tasks 3–4) ✓; IR-level round-trip identity + stability (Task 5) ✓; box-with-hole example (Task 5) ✓; shared `formats/fcstd.py` codec (Task 2) ✓; importer/exporter packages with Fusion 360 stub preserved (Tasks 3–4) ✓; AI SDK `DOMAIN_VOCAB` + `few_shot` + parametrized tests (Task 6) ✓; spec 0.5.0 (Task 1) ✓; README + CHANGELOG (Task 7) ✓; tests all offline ✓.
- **Refinements from the spec (intentional):** (1) mechanical models imported from `forgelab.spec.mechanical` (NOT re-exported top-level) to avoid shadowing the hardware `Pad`; (2) the codec operates on an `FcDocument(objects, name, generator)` so document meta round-trips for the identity guarantee.
- **Type/name consistency:** `FcDocument`/`FcObject`/`FcProperty`/`FcstdError`/`read_document`/`read_objects`/`write_fcstd`; node constants `NODE_PART/BODY/SKETCH/PAD/POCKET`; `_NODE_BY_FCTYPE`/`_FCTYPE_BY_NODE`/`_FIELDS`/`_MODEL_BY_NODE`; `FreeCADImporter`/`FreeCADExporter`/`FreeCADParseError` used consistently across tasks.
- **Boundary:** `formats/fcstd.py` is vocab-agnostic; mechanical importer imports only spec+formats; exporter imports only spec+formats; neither imports the other or `forgelab.core`.
