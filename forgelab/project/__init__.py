"""ForgeLab projects: tie multiple domain documents together with shared
dimensions and informational cross-domain constraints."""

from forgelab.project.constraints import check_constraint, check_constraints
from forgelab.project.export import (
    DEFAULT_TOOL_BY_DOMAIN,
    EXTENSION_BY_TOOL,
    default_tool_for_domain,
    extension_for_tool,
)
from forgelab.project.inference import infer_shared
from forgelab.project.model import (
    PROJECT_EXTENSION,
    Constraint,
    Project,
    dump_project,
    load_project_file,
    parse_project,
)

__all__ = [
    "PROJECT_EXTENSION",
    "Constraint",
    "Project",
    "dump_project",
    "load_project_file",
    "parse_project",
    "infer_shared",
    "check_constraint",
    "check_constraints",
    "DEFAULT_TOOL_BY_DOMAIN",
    "EXTENSION_BY_TOOL",
    "default_tool_for_domain",
    "extension_for_tool",
]
