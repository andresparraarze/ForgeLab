"""Clean, parse, and validate raw LLM output into a ForgeDocument."""

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from forgelab.core import validate
from forgelab.core.errors import LLMOutputError
from forgelab.sdk.schema import DOMAIN_VOCAB
from forgelab.spec import ForgeDocument, Node

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(raw: str) -> str:
    """Strip Markdown fences/prose and return the first balanced JSON object."""
    text = raw.strip()
    fence = _FENCE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise LLMOutputError("No JSON object found in LLM output.")
    depth = 0
    # Props are numeric/geometric with short identifier strings, so a naive
    # brace counter is sufficient; arbitrary text values would need a
    # string-aware scanner.
    for i in range(start, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # Braces never balanced — return from opening brace so json.loads can report
    # the real parse error with the "not valid JSON" message.
    return text[start:]


def _validate_node_props(node: Node, vocab: dict[str, type[BaseModel]], where: str) -> None:
    model = vocab.get(node.type)
    if model is None:
        raise LLMOutputError(
            f"{where}: unknown node type {node.type!r}; valid types: {sorted(vocab)}"
        )
    try:
        model.model_validate(node.props)
    except ValidationError as exc:
        raise LLMOutputError(f"{where} (type {node.type!r}) has invalid props: {exc}") from exc
    for i, child in enumerate(node.children):
        _validate_node_props(child, vocab, f"{where} > child[{i}] id={child.id!r}")


def validate_llm_output(raw: str | dict[str, Any], domain: str | None = None) -> ForgeDocument:
    """Turn raw LLM output (text or dict) into a validated ForgeDocument.

    Raises:
        LLMOutputError: with a message naming exactly what the LLM got wrong.
    """
    if isinstance(raw, dict):
        data: dict[str, Any] = raw
    else:
        payload = _extract_json(raw)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"LLM output is not valid JSON: {exc}") from exc

    try:
        document = validate(data)
    except LLMOutputError:
        raise
    except Exception as exc:
        raise LLMOutputError(f"LLM output failed ForgeLab validation: {exc}") from exc

    if domain is not None and document.domain.value != domain:
        raise LLMOutputError(
            f"Expected domain {domain!r} but document declares {document.domain.value!r}."
        )

    vocab = DOMAIN_VOCAB.get(document.domain.value)
    if vocab is None:
        raise LLMOutputError(f"No vocabulary registered for domain {document.domain.value!r}.")
    for i, node in enumerate(document.nodes):
        _validate_node_props(node, vocab, f"nodes[{i}] id={node.id!r}")

    return document
