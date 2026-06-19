import math

import pytest

from forgelab.calc import (
    calculate_board_layout,
    calculate_pad_positions,
    calculate_polygon,
    calculate_rotation_matrix,
    calculate_trace_width,
)


# --------------------------------------------------------------------------- #
# calculate_pad_positions
# --------------------------------------------------------------------------- #
def test_pad_positions_dip_dual_row_numbering_and_offsets():
    pads = calculate_pad_positions("DIP", pitch=2.54, count=8)
    assert len(pads) == 8
    # Pin 1 is top-left; the left column holds pins 1-4, the right column 5-8.
    assert pads[0] == {"number": "1", "at": [-3.81, 3.81]}
    assert pads[4] == {"number": "5", "at": [3.81, -3.81]}
    assert pads[7] == {"number": "8", "at": [3.81, 3.81]}
    left = [p for p in pads if p["at"][0] < 0]
    right = [p for p in pads if p["at"][0] > 0]
    assert [p["number"] for p in left] == ["1", "2", "3", "4"]
    assert [p["number"] for p in right] == ["5", "6", "7", "8"]
    positions = [tuple(p["at"]) for p in pads]
    assert len(set(positions)) == len(positions)  # no pad stacks on another


def test_pad_positions_soic_default_row_spacing_differs_from_dip():
    soic = calculate_pad_positions("SOIC", pitch=1.27, count=8)
    # SOIC rows sit closer together than a DIP's 7.62 mm.
    assert abs(soic[0]["at"][0]) == pytest.approx(2.7)


def test_pad_positions_single_row_lays_out_along_x():
    pads = calculate_pad_positions("SOP", pitch=2.0, count=3, dual_row=False)
    assert [p["at"] for p in pads] == [[-2.0, 0.0], [0.0, 0.0], [2.0, 0.0]]


def test_pad_positions_custom_row_spacing_is_honored():
    pads = calculate_pad_positions("DIP", pitch=2.54, count=4, row_spacing=10.0)
    assert abs(pads[0]["at"][0]) == 5.0


def test_pad_positions_qfp_is_four_sided_ccw():
    pads = calculate_pad_positions("QFP", pitch=0.5, count=16)
    assert len(pads) == 16
    assert pads[0] == {"number": "1", "at": [-1.25, 0.75]}  # left side, top
    assert pads[4] == {"number": "5", "at": [-0.75, -1.25]}  # bottom side, left
    assert pads[8] == {"number": "9", "at": [1.25, -0.75]}  # right side, bottom
    assert pads[12] == {"number": "13", "at": [0.75, 1.25]}  # top side, right
    positions = [tuple(p["at"]) for p in pads]
    assert len(set(positions)) == 16


def test_pad_positions_dual_row_rejects_odd_count():
    with pytest.raises(ValueError, match="even"):
        calculate_pad_positions("SOIC", pitch=1.27, count=7)


def test_pad_positions_qfp_rejects_count_not_divisible_by_four():
    with pytest.raises(ValueError, match="divisible by 4"):
        calculate_pad_positions("QFP", pitch=0.5, count=10)


def test_pad_positions_unknown_footprint_raises():
    with pytest.raises(ValueError, match="footprint_type"):
        calculate_pad_positions("BGA", pitch=0.8, count=16)


# --------------------------------------------------------------------------- #
# calculate_polygon
# --------------------------------------------------------------------------- #
def test_polygon_square_vertices_on_circle():
    verts = calculate_polygon(sides=4, radius=1.0)
    assert len(verts) == 8  # flat [x, y, x, y, ...]
    assert verts[0] == pytest.approx(1.0)
    assert verts[1] == pytest.approx(0.0, abs=1e-9)
    # Every vertex lies on the radius-1 circle about the origin.
    for i in range(0, len(verts), 2):
        x, y = verts[i], verts[i + 1]
        assert math.hypot(x, y) == pytest.approx(1.0)


def test_polygon_octagon_has_sixteen_values():
    assert len(calculate_polygon(sides=8, radius=2.5)) == 16


def test_polygon_center_offset_is_applied():
    verts = calculate_polygon(sides=4, radius=1.0, center=[10.0, 5.0])
    assert verts[0] == pytest.approx(11.0)
    assert verts[1] == pytest.approx(5.0, abs=1e-9)


def test_polygon_rejects_fewer_than_three_sides():
    with pytest.raises(ValueError, match="at least 3"):
        calculate_polygon(sides=2, radius=1.0)


# --------------------------------------------------------------------------- #
# calculate_rotation_matrix (quaternion)
# --------------------------------------------------------------------------- #
def test_rotation_zero_is_identity_quaternion():
    assert calculate_rotation_matrix(0.0) == [0.0, 0.0, 0.0, 1.0]


def test_rotation_ninety_about_y():
    q = calculate_rotation_matrix(90.0)  # default axis is Y (the up axis)
    assert q[0] == pytest.approx(0.0)
    assert q[1] == pytest.approx(math.sqrt(2) / 2)
    assert q[2] == pytest.approx(0.0)
    assert q[3] == pytest.approx(math.sqrt(2) / 2)


def test_rotation_axis_selection():
    qx = calculate_rotation_matrix(180.0, axis="x")
    assert qx[0] == pytest.approx(1.0)
    assert qx[3] == pytest.approx(0.0, abs=1e-9)


def test_rotation_quaternion_is_unit_length():
    q = calculate_rotation_matrix(37.0, axis="z")
    assert math.sqrt(sum(c * c for c in q)) == pytest.approx(1.0)


def test_rotation_bad_axis_raises():
    with pytest.raises(ValueError, match="axis"):
        calculate_rotation_matrix(45.0, axis="w")


# --------------------------------------------------------------------------- #
# calculate_trace_width (IPC-2221)
# --------------------------------------------------------------------------- #
def test_trace_width_known_external_value():
    # 1 A, 1 oz copper, 10 C rise, external ≈ 0.30 mm (matches IPC-2221 calculators).
    assert calculate_trace_width(1.0, 1.0, 10.0) == pytest.approx(0.30, abs=0.02)


def test_trace_width_scales_with_current():
    narrow = calculate_trace_width(1.0, 1.0, 10.0)
    wide = calculate_trace_width(5.0, 1.0, 10.0)
    assert wide > narrow


def test_trace_width_internal_is_wider_than_external():
    external = calculate_trace_width(2.0, 1.0, 10.0, external=True)
    internal = calculate_trace_width(2.0, 1.0, 10.0, external=False)
    assert internal > external


def test_trace_width_rejects_nonpositive_current():
    with pytest.raises(ValueError, match="current"):
        calculate_trace_width(0.0, 1.0, 10.0)


# --------------------------------------------------------------------------- #
# calculate_board_layout
# --------------------------------------------------------------------------- #
def test_board_layout_grid_within_margin():
    placements = calculate_board_layout(4, board_width=20.0, board_height=20.0, margin=2.0)
    assert [p["reference"] for p in placements] == ["U1", "U2", "U3", "U4"]
    for p in placements:
        x, y = p["at"]
        assert 2.0 <= x <= 18.0
        assert 2.0 <= y <= 18.0
    positions = [tuple(p["at"]) for p in placements]
    assert len(set(positions)) == 4  # nothing overlaps


def test_board_layout_custom_reference_prefix():
    placements = calculate_board_layout(2, 30.0, 10.0, margin=1.0, reference_prefix="R")
    assert [p["reference"] for p in placements] == ["R1", "R2"]


def test_board_layout_rejects_empty():
    with pytest.raises(ValueError, match="component_count"):
        calculate_board_layout(0, 20.0, 20.0, margin=2.0)


def test_board_layout_rejects_margin_larger_than_board():
    with pytest.raises(ValueError, match="margin"):
        calculate_board_layout(4, 10.0, 10.0, margin=6.0)
