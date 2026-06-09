"""The ForgeLab IR data models.

These models are intentionally generic: a ForgeDocument is a typed envelope
(version + domain + metadata) wrapping a graph of generic ``Node`` objects.
Domain-specific node vocabularies are layered on top in later work.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Domain(StrEnum):
    """Launch domains ForgeLab targets."""

    HARDWARE = "hardware"
    MECHANICAL = "mechanical"
    THREED = "threed"


class DocumentMeta(BaseModel):
    """Free-form-ish metadata about a document."""

    model_config = ConfigDict(extra="allow")

    name: str
    generator: str | None = None
    description: str | None = None


class Node(BaseModel):
    """A generic node in the ForgeLab design graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)
    children: list[Node] = Field(default_factory=list)


class ForgeDocument(BaseModel):
    """Root of a ForgeLab design document.

    ``forgelab_version`` declares which spec version the document conforms to.
    """

    model_config = ConfigDict(extra="forbid")

    forgelab_version: str
    domain: Domain
    meta: DocumentMeta
    nodes: list[Node] = Field(default_factory=list)


Node.model_rebuild()
