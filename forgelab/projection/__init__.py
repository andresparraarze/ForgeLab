"""Context projection layers.

Reduce a validated ForgeDocument to just the fields a task needs — metadata,
topology, geometry, or full — so an agent never receives data it will not use.
The stripping happens inside ForgeLab; the projected dict is all that leaves.
"""

from forgelab.projection.projector import PROJECTION_LEVELS, project
from forgelab.projection.schema import projection_schema

__all__ = ["project", "projection_schema", "PROJECTION_LEVELS"]
