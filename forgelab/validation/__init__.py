"""Domain-specific constraint sanity checks layered on top of IR validation."""

from forgelab.validation.hardware import check_hardware
from forgelab.validation.mechanical import check_mechanical

__all__ = ["check_hardware", "check_mechanical"]
