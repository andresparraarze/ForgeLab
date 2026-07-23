"""Domain-specific constraint sanity checks layered on top of IR validation."""

from forgelab.validation.fabrication import (
    check_fab_rules,
    check_gerber_completeness,
    fab_profile_names,
    fab_profiles,
)
from forgelab.validation.hardware import check_hardware
from forgelab.validation.mechanical import check_mechanical
from forgelab.validation.threed import check_threed

__all__ = [
    "check_hardware",
    "check_mechanical",
    "check_threed",
    "check_fab_rules",
    "check_gerber_completeness",
    "fab_profile_names",
    "fab_profiles",
]
