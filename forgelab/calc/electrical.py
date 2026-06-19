"""Electrical sizing helpers (IPC-2221 trace width)."""

from __future__ import annotations

# IPC-2221 constants.
_K_EXTERNAL = 0.048
_K_INTERNAL = 0.024
_OZ_TO_MILS = 1.378  # 1 oz/ft^2 of copper is ~1.378 mils thick.
_MILS_TO_MM = 0.0254


def calculate_trace_width(
    current_amps: float,
    copper_weight_oz: float = 1.0,
    temp_rise_c: float = 10.0,
    external: bool = True,
) -> float:
    """Recommended PCB trace width in millimetres, per IPC-2221.

    Args:
        current_amps: continuous current the trace must carry, in amperes.
        copper_weight_oz: copper thickness in ounces per square foot (1 oz ≈
            0.035 mm). Defaults to 1.0.
        temp_rise_c: allowable conductor temperature rise above ambient, in
            degrees Celsius. Defaults to 10.0.
        external: ``True`` for an outer-layer trace (better cooling, narrower);
            ``False`` for an inner-layer trace (needs more copper). Defaults to
            external.

    Returns:
        The minimum trace width in millimetres (rounded to 4 decimals).
    """
    if current_amps <= 0:
        raise ValueError("current_amps must be > 0")
    if copper_weight_oz <= 0:
        raise ValueError("copper_weight_oz must be > 0")
    if temp_rise_c <= 0:
        raise ValueError("temp_rise_c must be > 0")
    k = _K_EXTERNAL if external else _K_INTERNAL
    # IPC-2221: I = k * dT^0.44 * A^0.725  ->  A = (I / (k * dT^0.44))^(1/0.725).
    area_mils2 = (current_amps / (k * temp_rise_c**0.44)) ** (1.0 / 0.725)
    thickness_mils = copper_weight_oz * _OZ_TO_MILS
    width_mils = area_mils2 / thickness_mils
    return round(width_mils * _MILS_TO_MM, 4)
