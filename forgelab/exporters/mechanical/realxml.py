"""Build a genuine FreeCAD ``Document.xml`` from ForgeLab mechanical models.

The output matches the schema FreeCAD itself writes (validated against
FreeCAD 1.1): ``App::Part`` / ``PartDesign::Body`` / ``Sketcher::SketchObject``
with real ``Part::GeomLineSegment`` / ``Part::GeomCircle`` serialization, and
``PartDesign::Pad`` / ``PartDesign::Pocket`` features. No ``.brp`` shape files
are written — FreeCAD recomputes all shapes from the parametric definitions on
load. Notes pinned down experimentally:

- ``Properties Count`` counts only ``<Property>`` elements (``_Property``
  declarations are counted by ``TransientCount``); a mismatch aborts parsing.
- FreeCAD ignores a plain ``Placement`` on a sketch inside a Body, so each
  body owns an ``App::Origin`` and sketches attach to its datum planes via
  ``AttachmentSupport`` + ``MapMode`` (FlatFace); orientation is written into
  the axis-angle form FreeCAD reads, not just the quaternion.
- A feature's ``BaseFeature`` link is required for cuts to apply.
- Object declarations are marked ``Touched="1"`` so a plain recompute on open
  rebuilds geometry (no ``.brp`` shapes are stored).

Depends only on ``forgelab.spec`` (boundary rule).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import NamedTuple

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

# Quaternion (x, y, z, w) for each datum plane, taken from FreeCAD 1.1 output.
_PLANE_QUAT: dict[str, tuple[float, float, float, float]] = {
    "XY_Plane": (0.0, 0.0, 0.0, 1.0),
    "XZ_Plane": (0.7071067811865475, 0.0, 0.0, 0.7071067811865476),
    "YZ_Plane": (0.5, 0.5, 0.5, 0.5000000000000001),
}
_IDENTITY_QUAT = (0.0, 0.0, 0.0, 1.0)

# In-plane (u, v) basis + normal for each datum plane, used to lift 2D sketch
# coordinates into world space when estimating the part's bounding box.
_PLANE_BASIS: dict[str, tuple[tuple[float, float, float], ...]] = {
    "XY_Plane": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "XZ_Plane": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "YZ_Plane": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
}

# Agents spell the sketch plane many ways ("XY", "xy", "Front", "Top", a bare
# "" default). FreeCAD's datum planes are named XY_Plane / XZ_Plane / YZ_Plane,
# so normalize any reasonable spelling to one of those (FreeCAD UI view names
# map: Top->XY, Front->XZ, Right->YZ). Anything unrecognized falls back to XY
# rather than silently dropping the sketch's attachment.
_PLANE_ALIASES = {
    "XY": "XY_Plane",
    "XY_PLANE": "XY_Plane",
    "TOP": "XY_Plane",
    "XZ": "XZ_Plane",
    "XZ_PLANE": "XZ_Plane",
    "FRONT": "XZ_Plane",
    "YZ": "YZ_Plane",
    "YZ_PLANE": "YZ_Plane",
    "RIGHT": "YZ_Plane",
}


def _normalize_plane(plane: str) -> str:
    """Map any agent plane spelling to a FreeCAD datum plane (default XY)."""
    return _PLANE_ALIASES.get(plane.strip().upper(), "XY_Plane")


def _f(value: float) -> str:
    return f"{float(value):.16f}"


def _axis_angle(x: float, y: float, z: float, w: float) -> tuple[float, float, float, float]:
    """Quaternion (x, y, z, w) -> (angle, axis_x, axis_y, axis_z).

    FreeCAD reads the axis-angle form of a placement, so it must be written
    consistently with the quaternion or non-identity rotations are dropped.
    """
    w = max(-1.0, min(1.0, w))
    angle = 2.0 * math.acos(w)
    sin_half = math.sqrt(max(0.0, 1.0 - w * w))
    if sin_half < 1e-12:
        return 0.0, 1.0, 0.0, 0.0
    return angle, x / sin_half, y / sin_half, z / sin_half


def fc_name(node_id: str) -> str:
    """A FreeCAD-legal internal object name for an IR node id."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", node_id)
    if not name or name[0].isdigit():
        name = f"N_{name}"
    return name


def _prop(name: str, ptype: str, body: str) -> str:
    return f'<Property name="{name}" type="{ptype}">{body}</Property>'


def _placement_xml(position: Sequence[float], rotation: Sequence[float]) -> str:
    px, py, pz = position
    q0, q1, q2, q3 = rotation
    angle, ox, oy, oz = _axis_angle(q0, q1, q2, q3)
    return _prop(
        "Placement",
        "App::PropertyPlacement",
        f'<PropertyPlacement Px="{_f(px)}" Py="{_f(py)}" Pz="{_f(pz)}" '
        f'Q0="{_f(q0)}" Q1="{_f(q1)}" Q2="{_f(q2)}" Q3="{_f(q3)}" '
        f'A="{_f(angle)}" Ox="{_f(ox)}" Oy="{_f(oy)}" Oz="{_f(oz)}"/>',
    )


def _placement(placement: Placement) -> str:
    return _placement_xml(placement.position, placement.rotation)


def _sketch_placement(sketch: Sketch) -> str:
    """Orient a sketch by its explicit rotation, else by its named datum plane.

    FreeCAD recomputes an attached sketch's Placement from its attachment, so
    this is the pre-recompute value; it still matters for sketches that aren't
    attached (non-standard plane).
    """
    rotation = tuple(sketch.placement.rotation)
    if rotation == _IDENTITY_QUAT:
        rotation = _PLANE_QUAT.get(_normalize_plane(sketch.plane), _IDENTITY_QUAT)
    return _placement_xml(sketch.placement.position, rotation)


def _attachment_offset(placement: Placement) -> str:
    px, py, pz = placement.position
    q0, q1, q2, q3 = placement.rotation
    angle, ox, oy, oz = _axis_angle(q0, q1, q2, q3)
    return _prop(
        "AttachmentOffset",
        "App::PropertyPlacement",
        f'<PropertyPlacement Px="{_f(px)}" Py="{_f(py)}" Pz="{_f(pz)}" '
        f'Q0="{_f(q0)}" Q1="{_f(q1)}" Q2="{_f(q2)}" Q3="{_f(q3)}" '
        f'A="{_f(angle)}" Ox="{_f(ox)}" Oy="{_f(oy)}" Oz="{_f(oz)}"/>',
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
    model: Pad | Pocket, profile_fcname: str, base_feature: str | None, fallback_length: float
) -> list[str]:
    # PartDesign::Pocket Type enumeration (verified against FreeCAD 1.1):
    # 0=Length, 1=ThroughAll, 2=UpToFirst, ... — so through-all is Type 1.
    through_all = isinstance(model, Pocket) and model.through_all
    type_value = 1 if through_all else 0
    # FreeCAD never stores Length=0 for a feature; fall back to a part-scaled
    # length so a length isn't required for a through-all (where it is ignored)
    # and a degenerate length=0 still produces a real cut/extrude.
    length = model.length if model.length > 0 else fallback_length
    # A ThroughAll pocket cuts in ONE direction; if its sketch sits on the far
    # side of the solid (Reversed not set), it removes nothing — the live bug
    # where the bore left volume unchanged. Midplane makes it cut symmetrically
    # through everything, so a through-hole always cuts regardless of pad
    # direction. (Length is irrelevant for ThroughAll; verified in FreeCAD 1.1.)
    midplane = model.midplane or through_all
    return [
        _label(model.name),
        _prop(
            "Profile",
            "App::PropertyLinkSub",
            f'<LinkSub value="{profile_fcname}" count="0"></LinkSub>',
        ),
        _prop("Length", "App::PropertyLength", f'<Float value="{_f(length)}"/>'),
        _prop("Type", "App::PropertyEnumeration", f'<Integer value="{type_value}"/>'),
        _bool("Reversed", model.reversed),
        _bool("Midplane", midplane),
        *([_link("BaseFeature", base_feature)] if base_feature else []),
    ]


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
    return _placement_xml((0.0, 0.0, 0.0), [float(v) for v in q])


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


def build_real_document_xml(items: list[tuple[str, str, AnyModel]], doc_name: str) -> RealDocument:
    """Render the FreeCAD-schema Document.xml + GuiDocument.xml for the items."""
    name_of = {node_id: fc_name(node_id) for node_id, _, _ in items}
    # Part-scaled fallback for features that arrive with length=0 (e.g. a
    # through-all pocket, where the length is ignored anyway).
    fallback_length = max(
        (m.length for _, _, m in items if isinstance(m, Pad | Pocket) and m.length > 0),
        default=10.0,
    )

    body_ids = [nid for nid, ntype, _ in items if ntype == NODE_BODY]
    # A feature's ``body`` may reference its body by node id, by the body's
    # label/name, or (in a single-body part) be left blank/stale. Resolve all of
    # these to a body node id so the feature is grouped and — for sketches —
    # attached to that body's datum plane. Without this, a sketch whose body
    # link does not match a node id silently loses its AttachmentSupport.
    body_label_to_id: dict[str, str] = {}
    for nid, ntype, model in items:
        if ntype == NODE_BODY:
            body_label_to_id.setdefault(getattr(model, "name", ""), nid)
    body_id_set = set(body_ids)
    only_body = body_ids[0] if len(body_ids) == 1 else None

    def resolve_body(ref: str) -> str | None:
        if ref in body_id_set:
            return ref
        if ref in body_label_to_id:
            return body_label_to_id[ref]
        return only_body  # single-body part: an unmatched ref must mean that body

    features_of: dict[str, list[str]] = {b: [] for b in body_ids}
    solids_of: dict[str, list[str]] = {b: [] for b in body_ids}
    sketches_of: dict[str, list[str]] = {b: [] for b in body_ids}
    for nid, ntype, model in items:
        if ntype in _FEATURES:
            owner = resolve_body(getattr(model, "body", ""))
            if owner is not None:
                features_of[owner].append(nid)
                if ntype == NODE_SKETCH:
                    sketches_of[owner].append(nid)
                if ntype in _SOLID_FEATURES:
                    solids_of[owner].append(nid)

    # A Pad/Pocket ``profile`` may reference its sketch by node id, by the
    # sketch's label/name, or be stale; resolve the same way the body link is
    # (id -> label -> the sole sketch of the feature's body) so the Profile link
    # is never written empty ("PlatePad no object linked" on open otherwise).
    sketch_ids = {nid for nid, ntype, _ in items if ntype == NODE_SKETCH}
    sketch_label_to_id: dict[str, str] = {}
    for nid, ntype, model in items:
        if ntype == NODE_SKETCH:
            sketch_label_to_id.setdefault(getattr(model, "name", ""), nid)

    def resolve_profile(model: Pad | Pocket) -> str:
        ref = model.profile
        if ref in sketch_ids:
            return name_of[ref]
        if ref in sketch_label_to_id:
            return name_of[sketch_label_to_id[ref]]
        body = resolve_body(getattr(model, "body", ""))
        if body is not None and len(sketches_of[body]) == 1:
            return name_of[sketches_of[body][0]]
        return ""

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

    # Visible on open: each body container and its tip — the last solid feature
    # in the chain, whose shape is the fully-cut solid (base pad minus every
    # pocket). This is FreeCAD's normal PartDesign display state: the body shows
    # the tip shape and the body node isn't greyed-out in the tree. Intermediate
    # features, sketches and origin datums stay hidden.
    visible_names: set[str] = set()
    for nid, ntype, _ in items:
        if ntype == NODE_BODY:
            visible_names.add(name_of[nid])
    for solids in solids_of.values():
        if solids:
            visible_names.add(name_of[solids[-1]])
    object_names: list[str] = []

    decls = []
    datas = []
    extra_objects: list[tuple[str, str, list[str]]] = []
    for nid, ntype, model in items:
        fcname = name_of[nid]
        object_names.append(fcname)
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
            # Each body owns an Origin; sketches attach to its datum planes.
            origin_objs = _origin_objects(fcname)
            extra_objects.extend(origin_objs)
            body_origin_name = origin_objs[-1][0]
            group = [name_of[f] for f in features_of[nid]]
            tip = name_of[solids_of[nid][-1]] if solids_of[nid] else ""
            props = [
                _label(model.name),
                _placement(model.placement),
                _link_list("Group", group),
                _link("Origin", body_origin_name),
            ]
            if tip:
                props.append(_link("Tip", tip))
        elif isinstance(model, Sketch):
            props = [
                _label(model.name),
                _sketch_placement(model),
                _geometry(model),
                _prop(
                    "Constraints",
                    "Sketcher::PropertyConstraintList",
                    '<ConstraintList count="0"></ConstraintList>',
                ),
            ]
            # Attach to the owning body's datum plane so orientation survives
            # (FreeCAD ignores a plain Placement on an in-body sketch). The body
            # is resolved by id, label, or single-body fallback; the plane is
            # normalized so any spelling ("XY", "Front", "") maps to a datum.
            body_id = resolve_body(model.body)
            if body_id is not None:
                body_fcname = name_of[body_id]
                plane_obj = f"{body_fcname}_{_normalize_plane(model.plane)}"
                props.append(
                    _prop(
                        "AttachmentSupport",
                        "App::PropertyLinkSubList",
                        f'<LinkSubList count="1"><Link obj="{plane_obj}" sub=""/></LinkSubList>',
                    )
                )
                props.append(_prop("MapMode", "App::PropertyEnumeration", '<Integer value="5"/>'))
                props.append(_attachment_offset(model.placement))
        else:  # pad / pocket
            assert isinstance(model, Pad | Pocket)
            base = base_of.get(nid)
            props = _feature_props(
                model, resolve_profile(model), name_of[base] if base else None, fallback_length
            )
        body_xml = "".join(props)
        datas.append(
            f'<Object name="{fcname}"><Properties Count="{len(props)}" TransientCount="0">'
            f"{body_xml}</Properties></Object>"
        )

    for fcname, fctype, props in extra_objects:
        decls.append(f'<Object type="{fctype}" name="{fcname}" Touched="1" />')
        object_names.append(fcname)
        datas.append(
            f'<Object name="{fcname}"><Properties Count="{len(props)}" TransientCount="0">'
            f"{''.join(props)}</Properties></Object>"
        )

    count = len(items) + len(extra_objects)
    label_prop = _prop("Label", "App::PropertyString", f'<String value="{_xml(doc_name)}"/>')
    document_xml = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!--\n FreeCAD Document, see https://www.freecad.org for more information...\n-->\n"
        f'<Document SchemaVersion="4" ProgramVersion="ForgeLab" FileVersion="1">'
        f'<Properties Count="1" TransientCount="0">{label_prop}</Properties>'
        f'<Objects Count="{count}">{"".join(decls)}</Objects>'
        f'<ObjectData Count="{count}">{"".join(datas)}</ObjectData>'
        f"</Document>\n"
    )
    gui_xml = _gui_document_xml(object_names, visible_names, _camera_settings(items))
    return RealDocument(document_xml, gui_xml)


class RealDocument(NamedTuple):
    """The two XML members of a FreeCAD .FCStd archive."""

    document_xml: str
    gui_document_xml: str


def _estimate_bounds(
    items: list[tuple[str, str, AnyModel]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """A conservative world-space AABB of the part.

    Lifts every sketch's 2D geometry into world space via its datum plane and
    extrudes it both ways along the plane normal by the largest feature length,
    so the box safely contains the solid regardless of pad direction.
    """
    depth = max((abs(m.length) for _, _, m in items if isinstance(m, Pad | Pocket)), default=10.0)
    depth = depth or 10.0
    pts: list[tuple[float, float, float]] = []
    for _nid, _ntype, model in items:
        if not isinstance(model, Sketch):
            continue
        u, v, n = _PLANE_BASIS.get(_normalize_plane(model.plane), _PLANE_BASIS["XY_Plane"])
        ox, oy, oz = model.placement.position
        flat: list[tuple[float, float]] = []
        for geo in model.geometry:
            if geo.geo_type == "line":
                x1, y1, x2, y2 = geo.points
                flat += [(x1, y1), (x2, y2)]
            else:
                cx, cy = geo.center
                flat += [(cx - geo.radius, cy - geo.radius), (cx + geo.radius, cy + geo.radius)]
        for x, y in flat:
            bx = ox + x * u[0] + y * v[0]
            by = oy + x * u[1] + y * v[1]
            bz = oz + x * u[2] + y * v[2]
            for s in (0.0, depth, -depth):
                pts.append((bx + s * n[0], by + s * n[1], bz + s * n[2]))
    if not pts:
        return (0.0, 0.0, 0.0), (depth, depth, depth)
    lo = (min(p[0] for p in pts), min(p[1] for p in pts), min(p[2] for p in pts))
    hi = (max(p[0] for p in pts), max(p[1] for p in pts), max(p[2] for p in pts))
    return lo, hi


def _camera_settings(items: list[tuple[str, str, AnyModel]]) -> str:
    """An isometric orthographic camera framing the whole part on open."""
    (x0, y0, z0), (x1, y1, z1) = _estimate_bounds(items)
    cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
    diag = math.dist((x0, y0, z0), (x1, y1, z1)) or 10.0
    dist = diag * 1.5
    off = dist / math.sqrt(3.0)  # camera sits along (+1, -1, +1) from the centre
    return (
        "OrthographicCamera {\n"
        "  viewportMapping ADJUST_CAMERA\n"
        f"  position {cx + off:.6f} {cy - off:.6f} {cz + off:.6f}\n"
        "  orientation 0.7429061 0.3077218 0.5944728 1.2171160\n"
        f"  nearDistance {max(0.1, dist - diag):.6f}\n"
        f"  farDistance {dist + diag:.6f}\n"
        "  aspectRatio 1\n"
        f"  focalDistance {dist:.6f}\n"
        f"  height {diag * 1.1:.6f}\n"
        "}\n"
    )


def _gui_document_xml(object_names: list[str], visible: set[str], camera: str) -> str:
    """A GuiDocument.xml giving every object a ViewProvider, plus a camera.

    A minimal ViewProvider (just ``Visibility``) is enough — FreeCAD fills the
    rest and ``DisplayMode`` defaults to the shaded "Flat Lines". Without this,
    the default view providers hide the solids and leave only the sketches
    visible as wireframe. The camera frames the part so it fits on open.
    """
    vps = []
    for name in object_names:
        value = "true" if name in visible else "false"
        vps.append(
            f'<ViewProvider name="{name}" expanded="0">'
            f'<Properties Count="1" TransientCount="0">'
            f'<Property name="Visibility" type="App::PropertyBool" status="1">'
            f'<Bool value="{value}"/></Property></Properties></ViewProvider>'
        )
    camera_attr = _xml(camera).replace("\n", "&#10;")
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f'<Document SchemaVersion="1"><ViewProviderData Count="{len(object_names)}">'
        f'{"".join(vps)}</ViewProviderData><Camera settings="{camera_attr}"/></Document>\n'
    )
