"""The ForgeLab AI SDK.

Ergonomic helpers for AI agents to build, read, and serialize ForgeLab IR
without touching Pydantic internals. Everything an agent emits is plain JSON.
"""

import json
from typing import Any

from forgelab.core import validate
from forgelab.core.errors import LLMOutputError
from forgelab.sdk.agent import ForgeAgent
from forgelab.sdk.prompts import few_shot, system_prompt
from forgelab.sdk.schema import DOMAIN_VOCAB, domain_schema
from forgelab.sdk.validation import validate_llm_output
from forgelab.spec import DocumentMeta, Domain, ForgeDocument
from forgelab.spec.version import SPEC_VERSION

__all__ = [
    "new_document",
    "load",
    "dump",
    "SPEC_VERSION",
    "ForgeAgent",
    "domain_schema",
    "DOMAIN_VOCAB",
    "system_prompt",
    "few_shot",
    "validate_llm_output",
    "LLMOutputError",
]


def new_document(domain: str, name: str, generator: str = "forgelab-sdk") -> ForgeDocument:
    """Create an empty, version-stamped ForgeDocument for ``domain``."""
    return ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain(domain),
        meta=DocumentMeta(name=name, generator=generator),
    )


def load(data: str | dict[str, Any]) -> ForgeDocument:
    """Validate JSON text or a dict into a ForgeDocument."""
    parsed: dict[str, Any] = json.loads(data) if isinstance(data, str) else data
    return validate(parsed)


def dump(document: ForgeDocument, *, indent: int = 2) -> str:
    """Serialize a ForgeDocument to JSON text."""
    return document.model_dump_json(indent=indent)
