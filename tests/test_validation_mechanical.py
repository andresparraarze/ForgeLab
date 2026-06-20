"""Mechanical-domain constraint sanity checks (forgelab.validation.mechanical)."""

from forgelab.core import validate
from forgelab.mcp import tools
from forgelab.spec.version import SPEC_VERSION
from forgelab.validation import check_mechanical


def _doc(nodes, domain="mechanical"):
    return validate(
        {
            "forgelab_version": SPEC_VERSION,
            "domain": domain,
            "meta": {"name": "t", "generator": "test", "description": None},
            "nodes": nodes,
        }
    )


_PART = {"id": "Part", "type": "part", "props": {"name": "Part"}}
_BODY = {"id": "Body", "type": "body", "props": {"name": "Body", "part": "Part"}}


def _closed_square_geometry():
    # (0,0)->(1,0)->(1,1)->(0,1)->(0,0): every end meets another start.
    return [
        {"geo_type": "line", "points": [0.0, 0.0, 1.0, 0.0]},
        {"geo_type": "line", "points": [1.0, 0.0, 1.0, 1.0]},
        {"geo_type": "line", "points": [1.0, 1.0, 0.0, 1.0]},
        {"geo_type": "line", "points": [0.0, 1.0, 0.0, 0.0]},
    ]


def _sketch(geometry, sid="Sketch", body="Body"):
    return {
        "id": sid,
        "type": "sketch",
        "props": {"name": sid, "body": body, "plane": "XY_Plane", "geometry": geometry},
    }


def _pad(length, pid="Pad", body="Body", **extra):
    props = {"name": pid, "body": body, "profile": "Sketch", "length": length}
    props.update(extra)
    return {"id": pid, "type": "pad", "props": props}


def _pocket(length, pid="Pocket", body="Body", **extra):
    props = {"name": pid, "body": body, "profile": "Sketch", "length": length}
    props.update(extra)
    return {"id": pid, "type": "pocket", "props": props}


# --------------------------------------------------------------------------- #
# domain gating
# --------------------------------------------------------------------------- #
def test_non_mechanical_domains_are_skipped():
    for domain, nodes in (
        ("hardware", [{"id": "b", "type": "board", "props": {}}]),
        ("threed", [{"id": "s", "type": "scene", "props": {"name": "s"}}]),
    ):
        errors, warnings = check_mechanical(_doc(nodes, domain=domain))
        assert errors == []
        assert warnings == []


# --------------------------------------------------------------------------- #
# sketch closure (warning)
# --------------------------------------------------------------------------- #
def test_closed_loop_has_no_warning():
    doc = _doc([_PART, _BODY, _sketch(_closed_square_geometry()), _pad(5.0)])
    errors, warnings = check_mechanical(doc)
    assert errors == []
    assert warnings == []


def test_open_profile_warns():
    open_geo = [
        {"geo_type": "line", "points": [0.0, 0.0, 1.0, 0.0]},
        {"geo_type": "line", "points": [1.0, 0.0, 1.0, 1.0]},
    ]
    doc = _doc([_PART, _BODY, _sketch(open_geo), _pad(5.0)])
    errors, warnings = check_mechanical(doc)
    assert errors == []
    assert any("closed loop" in w for w in warnings)


# --------------------------------------------------------------------------- #
# pad length positive (error)
# --------------------------------------------------------------------------- #
def test_positive_pad_length_is_valid():
    doc = _doc([_PART, _BODY, _sketch(_closed_square_geometry()), _pad(3.0)])
    errors, _ = check_mechanical(doc)
    assert errors == []


def test_non_positive_pad_length_errors():
    doc = _doc([_PART, _BODY, _sketch(_closed_square_geometry()), _pad(0.0)])
    errors, _ = check_mechanical(doc)
    assert any("length <= 0" in e for e in errors)


def test_through_all_pad_skips_length_check():
    doc = _doc([_PART, _BODY, _sketch(_closed_square_geometry()), _pad(0.0, through_all=True)])
    errors, _ = check_mechanical(doc)
    assert errors == []


# --------------------------------------------------------------------------- #
# pocket depth bounds (error)
# --------------------------------------------------------------------------- #
def test_pocket_within_material_is_valid():
    doc = _doc([_PART, _BODY, _sketch(_closed_square_geometry()), _pad(5.0), _pocket(3.0)])
    errors, _ = check_mechanical(doc)
    assert errors == []


def test_pocket_deeper_than_material_errors():
    doc = _doc([_PART, _BODY, _sketch(_closed_square_geometry()), _pad(5.0), _pocket(8.0)])
    errors, _ = check_mechanical(doc)
    assert any("exceeds the available material" in e for e in errors)


def test_through_all_pocket_skips_depth_check():
    doc = _doc(
        [
            _PART,
            _BODY,
            _sketch(_closed_square_geometry()),
            _pad(5.0),
            _pocket(99.0, through_all=True),
        ]
    )
    errors, _ = check_mechanical(doc)
    assert errors == []


# --------------------------------------------------------------------------- #
# circle radius positive (error)
# --------------------------------------------------------------------------- #
def test_positive_circle_radius_is_valid():
    geo = [{"geo_type": "circle", "center": [0.0, 0.0], "radius": 2.0}]
    doc = _doc([_PART, _BODY, _sketch(geo), _pad(1.0)])
    errors, warnings = check_mechanical(doc)
    assert errors == []
    assert warnings == []  # a lone circle is closed, no closure warning


def test_non_positive_circle_radius_errors():
    geo = [{"geo_type": "circle", "center": [0.0, 0.0], "radius": 0.0}]
    doc = _doc([_PART, _BODY, _sketch(geo), _pad(1.0)])
    errors, _ = check_mechanical(doc)
    assert any("radius <= 0" in e for e in errors)


# --------------------------------------------------------------------------- #
# body reference consistency (error)
# --------------------------------------------------------------------------- #
def test_known_body_reference_is_valid():
    doc = _doc([_PART, _BODY, _sketch(_closed_square_geometry()), _pad(2.0)])
    errors, _ = check_mechanical(doc)
    assert errors == []


def test_unknown_body_reference_errors():
    doc = _doc([_PART, _BODY, _sketch(_closed_square_geometry()), _pad(2.0, body="Ghost")])
    errors, _ = check_mechanical(doc)
    assert any("references body 'Ghost'" in e for e in errors)


# --------------------------------------------------------------------------- #
# validate_document integration
# --------------------------------------------------------------------------- #
def _doc_dict(nodes):
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "mechanical",
        "meta": {"name": "t", "generator": "test", "description": None},
        "nodes": nodes,
    }


def test_validate_document_surfaces_warnings_but_stays_valid():
    open_geo = [{"geo_type": "line", "points": [0.0, 0.0, 1.0, 0.0]}]
    out = tools.validate_document(_doc_dict([_PART, _BODY, _sketch(open_geo), _pad(5.0)]))
    assert out["valid"] is True
    assert any("closed loop" in w for w in out["warnings"])


def test_validate_document_errors_make_invalid():
    nodes = [_PART, _BODY, _sketch(_closed_square_geometry()), _pad(0.0)]
    out = tools.validate_document(_doc_dict(nodes))
    assert out["valid"] is False
    assert "length <= 0" in out["error"]


def test_validate_document_clean_mechanical_has_no_warnings_key():
    nodes = [_PART, _BODY, _sketch(_closed_square_geometry()), _pad(5.0)]
    out = tools.validate_document(_doc_dict(nodes))
    assert out == {"valid": True}
