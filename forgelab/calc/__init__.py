"""Deterministic design-math utilities.

Pure-Python, dependency-free calculations (pad layouts, polygon vertices,
rotation quaternions, IPC-2221 trace widths, board placement grids) that the MCP
server exposes as tools so agents never compute geometry or electrical sizing
inline — and never make the arithmetic mistakes that come with it.
"""

from forgelab.calc.electrical import calculate_trace_width
from forgelab.calc.geometry import calculate_polygon, calculate_rotation_matrix
from forgelab.calc.layout import calculate_board_layout
from forgelab.calc.pads import calculate_pad_positions

__all__ = [
    "calculate_pad_positions",
    "calculate_polygon",
    "calculate_rotation_matrix",
    "calculate_trace_width",
    "calculate_board_layout",
]
