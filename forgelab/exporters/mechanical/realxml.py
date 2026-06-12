"""Build a genuine FreeCAD ``Document.xml`` from ForgeLab mechanical models.

The output matches the schema FreeCAD itself writes (validated against
FreeCAD 1.1): ``App::Part`` / ``PartDesign::Body`` / ``Sketcher::SketchObject``
with real ``Part::GeomLineSegment`` / ``Part::GeomCircle`` serialization, and
``PartDesign::Pad`` / ``PartDesign::Pocket`` features. No ``.brp`` shape files
are written — FreeCAD recomputes all shapes from the parametric definitions on
load. Notes pinned down experimentally:

- ``Properties Count`` counts only ``<Property>`` elements (``_Property``
  declarations are counted by ``TransientCount``); a mismatch aborts parsing.
- ``App::Origin`` objects are optional; sketches position via ``Placement``.
- A feature's ``BaseFeature`` link is required for cuts to apply.

Depends only on ``forgelab.spec`` (boundary rule).
"""

from __future__ import annotations

import re

from forgelab.spec.mechanical import (
    NODE_BODY,
    NODE_PAD,
    NODE_PART,
    NODE_POCKET,
    NODE_SKETCH,
    Body,
    Pad,
    Part,
    Placement,
    Pocket,
    Sketch,
)

_FCTYPE = {
    NODE_PART: "App::Part",
    NODE_BODY: "PartDesign::Body",
    NODE_SKETCH: "Sketcher::SketchObject",
    NODE_PAD: "PartDesign::Pad",
    NODE_POCKET: "PartDesign::Pocket",
}

_FEATURES = (NODE_SKETCH, NODE_PAD, NODE_POCKET)
_SOLID_FEATURES = (NODE_PAD, NODE_POCKET)

AnyModel = Part | Body | Sketch | Pad | Pocket


def _f(value: float) -> str:
    return f"{float(value):.16f}"


def fc_name(node_id: str) -> str:
    """A FreeCAD-legal internal object name for an IR node id."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", node_id)
    if not name or name[0].isdigit():
        name = f"N_{name}"
    return name


def _prop(name: str, ptype: str, body: str) -> str:
    return f'<Property name="{name}" type="{ptype}">{body}</Property>'


def _placement(placement: Placement) -> str:
    px, py, pz = placement.position
    q0, q1, q2, q3 = placement.rotation
    return _prop(
        "Placement",
        "App::PropertyPlacement",
        f'<PropertyPlacement Px="{_f(px)}" Py="{_f(py)}" Pz="{_f(pz)}" '
        f'Q0="{_f(q0)}" Q1="{_f(q1)}" Q2="{_f(q2)}" Q3="{_f(q3)}" '
        f'A="{_f(0)}" Ox="{_f(0)}" Oy="{_f(0)}" Oz="{_f(1)}"/>',
    )


def _label(name: str) -> str:
    return _prop("Label", "App::PropertyString", f'<String value="{_xml(name)}"/>')


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _link(name: str, target: str) -> str:
    return _prop(name, "App::PropertyLink", f'<Link value="{target}"/>')


def _link_list(name: str, targets: list[str]) -> str:
    links = "".join(f'<Link value="{t}"/>' for t in targets)
    return _prop(
        name, "App::PropertyLinkList", f'<LinkList count="{len(targets)}">{links}</LinkList>'
    )


def _geometry(sketch: Sketch) -> str:
    entries = []
    for i, geo in enumerate(sketch.geometry, start=1):
        ext = (
            f'<GeoExtensions count="1"><GeoExtension '
            f'type="Sketcher::SketchGeometryExtension" id="{i}" '
            f'internalGeometryType="0" '
            f'geometryModeFlags="00000000000000000000000000000000" '
            f'geometryLayer="0"/></GeoExtensions>'
        )
        if geo.geo_type == "line":
            x1, y1, x2, y2 = geo.points
            shape = (
                f'<LineSegment StartX="{_f(x1)}" StartY="{_f(y1)}" StartZ="{_f(0)}" '
                f'EndX="{_f(x2)}" EndY="{_f(y2)}" EndZ="{_f(0)}"/>'
            )
            gtype = "Part::GeomLineSegment"
        else:  # circle
            cx, cy = geo.center
            shape = (
                f'<Circle CenterX="{_f(cx)}" CenterY="{_f(cy)}" CenterZ="{_f(0)}" '
                f'NormalX="{_f(0)}" NormalY="{_f(0)}" NormalZ="{_f(1)}" '
                f'AngleXU="{_f(0)}" Radius="{_f(geo.radius)}"/>'
            )
            gtype = "Part::GeomCircle"
        entries.append(
            f'<Geometry type="{gtype}" id="{i}">{ext}{shape}<Construction value="0"/></Geometry>'
        )
    geometry_list = f'<GeometryList count="{len(entries)}">{"".join(entries)}</GeometryList>'
    return _prop("Geometry", "Part::PropertyGeometryList", geometry_list)


def _bool(name: str, value: bool) -> str:
    return _prop(name, "App::PropertyBool", f'<Bool value="{"true" if value else "false"}"/>')


def _feature_props(
    model: Pad | Pocket, name_of: dict[str, str], base_feature: str | None
) -> list[str]:
    props = [
        _label(model.name),
        _prop(
            "Profile",
            "App::PropertyLinkSub",
            f'<LinkSub value="{name_of.get(model.profile, "")}" count="0"></LinkSub>',
        ),
    ]
    if isinstance(model, Pocket):
        type_value = 1 if model.through_all else 0
        props.append(_prop("Length", "App::PropertyLength", f'<Float value="{_f(model.length)}"/>'))
    else:
        type_value = 0
        props.append(_prop("Length", "App::PropertyLength", f'<Float value="{_f(model.length)}"/>'))
    props.append(_prop("Type", "App::PropertyEnumeration", f'<Integer value="{type_value}"/>'))
    props.append(_bool("Reversed", model.reversed))
    props.append(_bool("Midplane", model.midplane))
    if base_feature:
        props.append(_link("BaseFeature", base_feature))
    return props


# App::Part requires a linked App::Origin to recompute; PartDesign::Body
# tolerates its absence. Standard origin feature set (type, role, quaternion),
# quaternions taken verbatim from a FreeCAD 1.1-authored document.
_ORIGIN_FEATURES = [
    ("App::Line", "X_Axis", ("0", "0", "0", "1")),
    ("App::Line", "Y_Axis", ("0.5", "0.5", "0.5", "0.5000000000000001")),
    ("App::Line", "Z_Axis", ("0.5", "-0.5", "0.5", "0.5000000000000001")),
    ("App::Plane", "XY_Plane", ("0", "0", "0", "1")),
    ("App::Plane", "XZ_Plane", ("0.7071067811865475", "0", "0", "0.7071067811865475")),
    ("App::Plane", "YZ_Plane", ("0.5", "0.5", "0.5", "0.5000000000000001")),
    ("App::Point", "Origin", ("0", "0", "0", "1")),
]


def _raw_placement(q: tuple[str, str, str, str]) -> str:
    return _prop(
        "Placement",
        "App::PropertyPlacement",
        f'<PropertyPlacement Px="{_f(0)}" Py="{_f(0)}" Pz="{_f(0)}" '
        f'Q0="{_f(float(q[0]))}" Q1="{_f(float(q[1]))}" '
        f'Q2="{_f(float(q[2]))}" Q3="{_f(float(q[3]))}" '
        f'A="{_f(0)}" Ox="{_f(0)}" Oy="{_f(0)}" Oz="{_f(1)}"/>',
    )


def _origin_objects(part_fcname: str) -> list[tuple[str, str, list[str]]]:
    """(fcname, fctype, props-xml) for an App::Origin and its features."""
    out: list[tuple[str, str, list[str]]] = []
    feature_names = []
    for fctype, role, q in _ORIGIN_FEATURES:
        fname = f"{part_fcname}_{role}" if fctype != "App::Point" else f"{part_fcname}_OriginPoint"
        feature_names.append(fname)
        out.append(
            (
                fname,
                fctype,
                [
                    _label(role),
                    _prop("Role", "App::PropertyString", f'<String value="{role}"/>'),
                    _raw_placement(q),
                ],
            )
        )
    origin_name = f"{part_fcname}_Origin"
    origin_props = [
        _label("Origin"),
        _link_list("OriginFeatures", feature_names),
        _raw_placement(("0", "0", "0", "1")),
    ]
    out.append((origin_name, "App::Origin", origin_props))
    return out


def build_real_document_xml(items: list[tuple[str, str, AnyModel]], doc_name: str) -> str:
    """Render FreeCAD-schema Document.xml for (node_id, node_type, model) items."""
    name_of = {node_id: fc_name(node_id) for node_id, _, _ in items}

    body_ids = [nid for nid, ntype, _ in items if ntype == NODE_BODY]
    features_of: dict[str, list[str]] = {b: [] for b in body_ids}
    solids_of: dict[str, list[str]] = {b: [] for b in body_ids}
    for nid, ntype, model in items:
        if ntype in _FEATURES:
            owner = getattr(model, "body", "")
            if owner in features_of:
                features_of[owner].append(nid)
                if ntype in _SOLID_FEATURES:
                    solids_of[owner].append(nid)
    bodies_of_part: dict[str, list[str]] = {}
    for nid, _ntype, model in items:
        if isinstance(model, Body) and model.part:
            bodies_of_part.setdefault(model.part, []).append(nid)

    base_of: dict[str, str | None] = {}
    for solids in solids_of.values():
        prev = None
        for nid in solids:
            base_of[nid] = prev
            prev = nid

    decls = []
    datas = []
    extra_objects: list[tuple[str, str, list[str]]] = []
    for nid, ntype, model in items:
        fcname = name_of[nid]
        # Touched="1": with no stored .brp shapes, FreeCAD only rebuilds
        # geometry for dirty objects — this makes recompute-on-open work.
        decls.append(f'<Object type="{_FCTYPE[ntype]}" name="{fcname}" Touched="1" />')
        props: list[str]
        if isinstance(model, Part):
            origin_objs = _origin_objects(fcname)
            extra_objects.extend(origin_objs)
            origin_name = origin_objs[-1][0]
            group = [origin_name] + [name_of[b] for b in bodies_of_part.get(nid, [])]
            props = [
                _label(model.name),
                _placement(model.placement),
                _link_list("Group", group),
                _link("Origin", origin_name),
            ]
        elif isinstance(model, Body):
            group = [name_of[f] for f in features_of[nid]]
            tip = name_of[solids_of[nid][-1]] if solids_of[nid] else ""
            props = [_label(model.name), _placement(model.placement), _link_list("Group", group)]
            if tip:
                props.append(_link("Tip", tip))
        elif isinstance(model, Sketch):
            props = [
                _label(model.name),
                _placement(model.placement),
                _geometry(model),
                _prop(
                    "Constraints",
                    "Sketcher::PropertyConstraintList",
                    '<ConstraintList count="0"></ConstraintList>',
                ),
            ]
        else:  # pad / pocket
            assert isinstance(model, Pad | Pocket)
            base = base_of.get(nid)
            props = _feature_props(model, name_of, name_of[base] if base else None)
        body_xml = "".join(props)
        datas.append(
            f'<Object name="{fcname}"><Properties Count="{len(props)}" TransientCount="0">'
            f"{body_xml}</Properties></Object>"
        )

    for fcname, fctype, props in extra_objects:
        decls.append(f'<Object type="{fctype}" name="{fcname}" Touched="1" />')
        datas.append(
            f'<Object name="{fcname}"><Properties Count="{len(props)}" TransientCount="0">'
            f"{''.join(props)}</Properties></Object>"
        )

    count = len(items) + len(extra_objects)
    label_prop = _prop("Label", "App::PropertyString", f'<String value="{_xml(doc_name)}"/>')
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!--\n FreeCAD Document, see https://www.freecad.org for more information...\n-->\n"
        f'<Document SchemaVersion="4" ProgramVersion="ForgeLab" FileVersion="1">'
        f'<Properties Count="1" TransientCount="0">{label_prop}</Properties>'
        f'<Objects Count="{count}">{"".join(decls)}</Objects>'
        f'<ObjectData Count="{count}">{"".join(datas)}</ObjectData>'
        f"</Document>\n"
    )


GUI_DOCUMENT_XML = (
    "<?xml version='1.0' encoding='utf-8'?>\n"
    '<Document SchemaVersion="1"><ViewProviderData Count="0"/>'
    '<Camera settings=""/></Document>\n'
)
