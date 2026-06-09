"""The ForgeLab intermediate representation (IR)."""

from forgelab.spec.hardware import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    BoardLayer,
    Component,
    DesignRules,
    Net,
    OutlineSegment,
    Pad,
)
from forgelab.spec.models import DocumentMeta, Domain, ForgeDocument, Node
from forgelab.spec.schema import json_schema
from forgelab.spec.version import SPEC_VERSION, is_compatible

__all__ = [
    "SPEC_VERSION",
    "is_compatible",
    "Domain",
    "DocumentMeta",
    "ForgeDocument",
    "Node",
    "json_schema",
    "NODE_BOARD",
    "NODE_COMPONENT",
    "NODE_NET",
    "BoardConstraints",
    "BoardLayer",
    "Component",
    "DesignRules",
    "Net",
    "OutlineSegment",
    "Pad",
]
