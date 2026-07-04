"""The ForgeLab Project model: a container tying multiple domain documents
together with shared dimensions and cross-domain constraints.

A project is *not* a domain document. It is a separate ``.forge.project`` JSON
file that references documents by path and holds a flat ``shared`` dimension
table — a single source of truth that every linked document can be checked
against (e.g. a board outline width informing an enclosure's inner width).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from forgelab.spec import SPEC_VERSION

PROJECT_EXTENSION = ".forge.project"


class Constraint(BaseModel):
    """One cross-domain coherence rule.

    Reports whether a value inside a target document agrees with a shared
    dimension (plus an optional ``offset``). Checking is informational for now:
    violations are reported but never block an export.
    """

    model_config = ConfigDict(extra="forbid")

    description: str = ""
    type: str = "min_value"
    source: str = Field(
        description="The shared dimension to compare against, e.g. 'shared.board_width'.",
    )
    target_document: str = Field(
        description="The key (in ``documents``) of the document the target value lives in.",
    )
    target_path: str = Field(
        description="An RFC 6901 JSON Pointer to the value inside the target document.",
    )
    offset: float = 0.0


class Project(BaseModel):
    """A ForgeLab project: linked documents, shared dimensions, constraints."""

    model_config = ConfigDict(extra="forbid")

    forgelab_version: str = SPEC_VERSION
    name: str
    description: str | None = None
    documents: dict[str, str] = Field(default_factory=dict)
    shared: dict[str, float] = Field(default_factory=dict)
    constraints: list[Constraint] = Field(default_factory=list)


def parse_project(data: dict[str, Any]) -> Project:
    """Validate a raw dict into a :class:`Project`."""
    return Project.model_validate(data)


def load_project_file(path: Path) -> Project:
    """Read and validate a ``.forge.project`` file from disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read project {str(path)!r}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"project {str(path)!r} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"project {str(path)!r} is not a JSON object")
    try:
        return parse_project(data)
    except ValidationError as exc:
        raise ValueError(f"project {str(path)!r} is not a valid ForgeLab project: {exc}") from exc


def dump_project(project: Project) -> str:
    """Serialize a project to canonical pretty JSON (trailing newline)."""
    return json.dumps(project.model_dump(mode="json"), indent=2) + "\n"
