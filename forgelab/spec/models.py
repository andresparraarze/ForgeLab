"""The ForgeLab IR data models.

These models are intentionally generic: a ForgeDocument is a typed envelope
(version + domain + metadata) wrapping a graph of generic ``Node`` objects.
Domain-specific node vocabularies are layered on top in later work.
"""

from __future__ import annotations

from collections.abc import Iterator
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

    def walk(self) -> Iterator[Node]:
        """Yield this node then all descendants, depth-first (pre-order)."""
        yield self
        for child in self.children:
            yield from child.walk()


class ForgeDocument(BaseModel):
    """Root of a ForgeLab design document.

    ``forgelab_version`` declares which spec version the document conforms to.
    """

    model_config = ConfigDict(extra="forbid")

    forgelab_version: str
    domain: Domain
    meta: DocumentMeta
    nodes: list[Node] = Field(default_factory=list)

    def walk(self) -> Iterator[Node]:
        """Yield every node in the document tree, depth-first (pre-order).

        Hierarchy may be expressed either as a flat ``nodes`` list or by nesting
        via ``Node.children``; consumers that need every node (e.g. exporters)
        should iterate ``walk()`` rather than ``nodes`` so nested nodes are not
        silently dropped.
        """
        for node in self.nodes:
            yield from node.walk()


Node.model_rebuild()
