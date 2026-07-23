"""Retrievable prompt templates that instruct any LLM to emit ForgeLab JSON."""

import json
from pathlib import Path

from forgelab.sdk.schema import DOMAIN_VOCAB
from forgelab.spec.version import SPEC_VERSION

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

# domain -> [(example user request, path to a valid .forge.json under examples/)]
_FEW_SHOT: dict[str, list[tuple[str, str]]] = {
    "hardware": [
        (
            "an Arduino Uno clone board",
            "hardware/arduino_uno.forge.json",
        ),
    ],
    "threed": [
        (
            "a sci-fi space station with a rotating ring, solar arrays, "
            "a docking port and a comm dish",
            "threed/space_station.forge.json",
        ),
        # Canonical organic-shape pattern: primitive + modifier stack
        # (subsurf/bevel/boolean) instead of hand-computed triangles.
        (
            "a smooth ergonomic handle with a thumb-rest indent",
            "threed/organic_handle.forge.json",
        ),
    ],
    "mechanical": [
        (
            "a NEMA17 stepper motor mount plate",
            "mechanical/motor_mount.forge.json",
        ),
    ],
}


# domain -> extra guidance appended to the system prompt (reference conventions,
# etc.). Keyed by domain so only the relevant note ships with each prompt.
_REFERENCE_HINTS: dict[str, str] = {
    "hardware": (
        'Pad placement: give every pad on a component its physical "at" '
        "offset — the pad's [x, y] position relative to the footprint origin in "
        "millimetres — so a multi-pin part spreads across its real package "
        'outline. For example a 4-pad SOIC: "at": [-1.5, -2.0], [1.5, -2.0], '
        '[1.5, 2.0], [-1.5, 2.0]. A pad with no "at" is placed on a fallback '
        "grid, so omitting it makes every pad collapse toward the origin instead "
        'of matching the real layout. Optionally set each pad\'s "size" '
        '([width, height]) and "shape" when known.'
    ),
    "threed": (
        'References between nodes always use the target node\'s top-level "id", '
        'never its display "name". An object\'s "mesh" prop must be a mesh '
        "node's id, and a primitive's \"material\" must be a material node's id. "
        "For example, given a material node "
        '{"id": "mat_red", "type": "material", "props": {"name": "vermilion", '
        '...}}, reference it as "material": "mat_red" (its id) — never '
        '"material": "vermilion" (its name). A reference that uses the display '
        "name will not resolve and the export will fail.\n\n"
        "Up axis: the threed domain is Y-up (the glTF convention). Author all "
        "geometry with the Y axis as up — put an object's height on the Y "
        "position/translation component, not Z. Do NOT use Z as up: glTF is "
        "Y-up and Blender's importer converts Y-up back to its own Z-up world, "
        "so a Z-up document gets double-converted and lands tipped on its side."
    ),
    "mechanical": (
        "Two modelling toolkits are available. PartDesign (sketch/pad/pocket) "
        "is for prismatic engineering parts — brackets, mounts, plates, "
        "enclosures — built by extruding and cutting closed 2D profiles. "
        "Sketch geometry is line, circle or arc. An arc is an OPEN segment of "
        'a circle — {"geo_type": "arc", "center": [x, y], "radius": r, '
        '"start_angle": a0, "end_angle": a1} with angles in DEGREES '
        "counter-clockwise from the +X axis, sweeping counter-clockwise from "
        "start to end — so its two endpoints join adjacent lines the way two "
        "lines join each other. Use arcs for rounded rectangles, slots and "
        "filleted 2D outlines instead of approximating them with a circle "
        "cut: a rounded rectangle is 4 straight edges plus 4 corner arcs "
        "(see examples/mechanical/rounded_rect_plate.forge.json). The "
        "Part workbench (loft/sweep/fillet/shell) is for organic or curved "
        "shapes — grips, handles, knobs, ergonomic surfaces — where FreeCAD's OCC "
        "kernel computes real NURBS geometry. The canonical organic pattern "
        "(see examples/mechanical/organic_grip.forge.json) is: stack several "
        "circle-profile sketches along the loft axis by giving each sketch a "
        "placement position [0, 0, z], loft through them in order via a loft "
        'node\'s "profiles" list (sketch node ids, at least 2), then soften '
        'the result with a fillet node whose "target" is the loft (omit '
        '"edges" to round every edge). Choose loft for ASYMMETRIC shapes whose '
        "cross-section changes along a path; choose revolve for SYMMETRIC "
        "round shapes — knobs, caps, bottle-like grips — where one closed "
        "profile sketch spun around an axis is easier to specify correctly "
        "than stacked loft sections. The canonical revolve pattern (see "
        "examples/mechanical/rounded_knob.forge.json) is: sketch the shape's "
        "half-outline as a closed line loop on the XZ plane, keep every point "
        "at x >= 0 (the profile may touch the Z axis but must not cross it), "
        'then revolve it with axis "Z" and angle 360 (smaller angles give '
        "partial revolves). Use sweep to drive a profile sketch "
        "along a path sketch, and shell to hollow a solid — list the faces to "
        'leave open in "faces_to_remove" (at least one face must stay open '
        "for the kernel to hollow it). Reach for loft/sweep/fillet/shell/"
        "revolve only when the shape genuinely curves; prismatic parts stay "
        "in sketch/pad/pocket. Every feature above works inside ONE body's "
        "chain, so to combine two SEPARATELY-BUILT solids use a boolean node: "
        '{"operation": "union"|"cut"|"common", "base": <node id>, "tools": '
        "[<node ids>]}, naming whole bodies (or a single solid feature). Model "
        "each part in its own body, then union them — that is how a plate and "
        "a boss become one part (see "
        "examples/mechanical/bracket_with_boss.forge.json). union and common "
        "take several tools at once; cut takes exactly one (chain booleans to "
        "cut more). Position the operands so they actually meet: FreeCAD "
        "reports NO error for a cut that removes nothing or an intersection "
        "that is empty — it returns an empty result instead."
    ),
}


def _check_domain(domain: str) -> None:
    if domain not in DOMAIN_VOCAB:
        raise KeyError(f"Unknown domain {domain!r}; valid domains: {sorted(DOMAIN_VOCAB)}")


def system_prompt(domain: str) -> str:
    """Return a system prompt instructing an LLM to emit valid ForgeLab JSON."""
    _check_domain(domain)
    node_types = ", ".join(sorted(DOMAIN_VOCAB[domain]))
    reference_hint = _REFERENCE_HINTS.get(domain)
    reference_block = f"{reference_hint}\n\n" if reference_hint else ""
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
        f"{reference_block}"
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
    examples: list[tuple[str, str]] = []
    for user, rel_path in _FEW_SHOT[domain]:
        document = json.loads((_EXAMPLES_DIR / rel_path).read_text())
        # The shipped file carries the version it was generated at; always show
        # the installed library's version so agents never copy a stale one.
        document["forgelab_version"] = SPEC_VERSION
        examples.append((user, json.dumps(document, indent=2)))
    return examples
