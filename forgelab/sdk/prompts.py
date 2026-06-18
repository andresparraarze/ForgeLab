"""Retrievable prompt templates that instruct any LLM to emit ForgeLab JSON."""

import json
from pathlib import Path

from forgelab.sdk.schema import DOMAIN_VOCAB
from forgelab.spec.version import SPEC_VERSION

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

# domain -> (example user request, path to a valid .forge.json under examples/)
_FEW_SHOT: dict[str, tuple[str, str]] = {
    "hardware": (
        "a 2-layer blinky LED board with one resistor and one LED",
        "hardware/blinky.forge.json",
    ),
    "threed": (
        "a single cube with a clearly visible red material",
        "threed/cube.forge.json",
    ),
    "mechanical": (
        "a 40x20x10 box with a through hole",
        "mechanical/box-with-hole.forge.json",
    ),
}


def _check_domain(domain: str) -> None:
    if domain not in DOMAIN_VOCAB:
        raise KeyError(f"Unknown domain {domain!r}; valid domains: {sorted(DOMAIN_VOCAB)}")


def system_prompt(domain: str) -> str:
    """Return a system prompt instructing an LLM to emit valid ForgeLab JSON."""
    _check_domain(domain)
    node_types = ", ".join(sorted(DOMAIN_VOCAB[domain]))
    return (
        "You are a design agent for ForgeLab, a universal JSON design "
        "interchange format. You emit ForgeLab documents that downstream tools "
        "compile into native design files.\n\n"
        "A ForgeLab document is a JSON object with these top-level keys:\n"
        f'  - "forgelab_version": must be "{SPEC_VERSION}" (the installed spec version)\n'
        f'  - "domain": must be exactly "{domain}"\n'
        '  - "meta": an object with at least a "name"\n'
        '  - "nodes": a list of nodes, each {"id", "type", "props", '
        '"children"}\n\n'
        f"For the {domain} domain the valid node types are: {node_types}. "
        'Each node\'s "props" must use only the exact field names defined by '
        "that type's schema — never invent fields. Scene hierarchy, when "
        'present, is expressed via a node\'s "children" list.\n\n'
        "Build the complete document in a single pass: decide on every node and "
        "all of its props up front and assemble the full design before you "
        "finish. Do not construct the document incrementally or call "
        "validate_document repeatedly to discover the shape — consult the schema "
        "first, then validate once at the end.\n\n"
        "Respond with ONLY a single JSON object conforming to the provided "
        "schema. No prose, no Markdown fences."
    )


def few_shot(domain: str) -> list[tuple[str, str]]:
    """Return (user_request, assistant_json) examples for ``domain``.

    The assistant JSON is loaded from shipped example files, so every example
    is guaranteed to be a valid ForgeLab document.
    """
    _check_domain(domain)
    user, rel_path = _FEW_SHOT[domain]
    document = json.loads((_EXAMPLES_DIR / rel_path).read_text())
    # The shipped file carries the version it was generated at; always show
    # the installed library's version so agents never copy a stale one.
    document["forgelab_version"] = SPEC_VERSION
    return [(user, json.dumps(document, indent=2))]
