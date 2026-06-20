"""ForgeLab MCP tool callables.

Plain functions wrapping the core compiler, registry, and AI SDK. ``server.py``
registers them with FastMCP. Each enforces its scope via ``require_scope`` (a
no-op over the unauthenticated stdio transport).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from forgelab.calc import (
    calculate_board_layout as _calc_board_layout,
)
from forgelab.calc import (
    calculate_pad_positions as _calc_pad_positions,
)
from forgelab.calc import (
    calculate_polygon as _calc_polygon,
)
from forgelab.calc import (
    calculate_rotation_matrix as _calc_rotation_matrix,
)
from forgelab.calc import (
    calculate_trace_width as _calc_trace_width,
)
from forgelab.core import UnknownToolError, default_registry, validate
from forgelab.core import validate as _core_validate
from forgelab.mcp.auth_bridge import require_scope
from forgelab.mcp.content import decode_content, encode_bytes
from forgelab.patch import PatchError, apply_patch, diff
from forgelab.projection import PROJECTION_LEVELS, project, projection_schema
from forgelab.sdk import DOMAIN_VOCAB, ForgeAgent, domain_schema, few_shot, system_prompt
from forgelab.validation import check_mechanical

_registry = default_registry()


def _resolve_path(path_str: str) -> Path:
    """Bare filenames land in FORGELAB_OUTPUT_DIR (or the cwd); paths pass through."""
    path = Path(path_str)
    if not path.is_absolute() and path.parent == Path("."):
        base = os.environ.get("FORGELAB_OUTPUT_DIR")
        return (Path(base) if base else Path.cwd()) / path
    return path


def _read_document_file(document_path: str) -> dict[str, Any]:
    """Read and JSON-parse a ``.forge.json`` from disk into a plain dict.

    Raises ``ValueError`` with an actionable message if the file is missing or
    is not a JSON object. A bare filename resolves against ``FORGELAB_OUTPUT_DIR``
    (the same place ``export_document`` writes), so the agent can round-trip a
    document by name without spelling out an absolute path.
    """
    path = _resolve_path(document_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read document {str(path)!r}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"document {str(path)!r} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"document {str(path)!r} is not a JSON object")
    return data


def _document_source(document: dict[str, Any] | None, document_path: str | None) -> dict[str, Any]:
    """Resolve a document from exactly one of an inline object or a file path.

    Raises ``ValueError`` if both or neither is given, or if the file cannot be
    read. Lets tools accept a path (keeping large JSON out of the agent's context
    window) while preserving the inline-document path unchanged.
    """
    if document is not None and document_path is not None:
        raise ValueError("pass either document or document_path, not both")
    if document_path is not None:
        return _read_document_file(document_path)
    if document is not None:
        return document
    raise ValueError("provide a document (inline) or a document_path to a .forge.json file")


def _check_projection(projection: str) -> str:
    if projection not in PROJECTION_LEVELS:
        raise ValueError(
            f"unknown projection {projection!r}; valid: {', '.join(PROJECTION_LEVELS)}"
        )
    return projection


def validate_document(
    document: dict[str, Any] | None = None,
    document_path: str | None = None,
    projection: str | None = None,
) -> dict[str, Any]:
    """Validate a ForgeLab document.

    Returns ``{"valid": bool, "error"?: str, "warnings"?: list[str]}``.

    Pass the document inline as ``document``, or pass ``document_path`` pointing at
    a ``.forge.json`` file on disk — ForgeLab reads and validates it without the
    agent ever loading the JSON into its context. A bare filename resolves against
    ``FORGELAB_OUTPUT_DIR``. Exactly one of the two must be given.

    For mechanical documents, lightweight constraint sanity checks run after the
    structural check (sketch closure, positive pad length, pocket depth bounds,
    positive circle radius, body-reference consistency). Fatal problems become
    ``error`` (and ``valid`` is False); non-fatal ones are returned in
    ``warnings`` without affecting ``valid``. These checks are skipped for the
    hardware and threed domains.

    projection: when set to a projection level (``metadata``, ``topology``,
    ``geometry`` or ``full``), a successful validation also returns a
    ``"projection"`` view of the document reduced to just that level's fields, so
    the agent gets back only the data it needs. Omit it for a plain validity
    result.
    """
    require_scope("forge:read")
    if projection is not None:
        _check_projection(projection)
    source = _document_source(document, document_path)
    try:
        document_model = validate(source)
    except Exception as exc:  # any validation failure is reported to the caller
        return {"valid": False, "error": str(exc)}

    # Domain sanity checks layer on top of structural validation. Errors are
    # fatal (valid=False); warnings are surfaced but non-fatal.
    errors, warnings = check_mechanical(document_model)
    if errors:
        result: dict[str, Any] = {"valid": False, "error": "; ".join(errors)}
        if warnings:
            result["warnings"] = warnings
        return result

    result = {"valid": True}
    if warnings:
        result["warnings"] = warnings
    if projection is not None:
        result["projection"] = project(document_model, projection)
    return result


def get_domain_schema(domain: str) -> dict[str, Any]:
    """Return the JSON Schema for a ForgeLab domain."""
    require_scope("forge:read")
    try:
        return domain_schema(domain)
    except KeyError as exc:
        raise ValueError(f"unknown domain: {domain!r}") from exc


def get_prompt(domain: str) -> dict[str, Any]:
    """Return the system prompt and a few-shot example for a domain."""
    require_scope("forge:read")
    try:
        return {"system": system_prompt(domain), "few_shot": few_shot(domain)}
    except KeyError as exc:
        raise ValueError(f"unknown domain: {domain!r}") from exc


def list_domains() -> list[str]:
    """List the ForgeLab domains the server understands."""
    require_scope("forge:read")
    return sorted(DOMAIN_VOCAB)


def list_formats() -> dict[str, dict[str, bool]]:
    """List registered format tools and their import/export availability."""
    require_scope("forge:read")
    return _registry.tool_names()


def _count_node_types(nodes: Any) -> Counter[str]:
    """Count node types over a raw node list, recursing into ``children``."""
    counts: Counter[str] = Counter()
    if not isinstance(nodes, list):
        return counts
    for node in nodes:
        if not isinstance(node, dict):
            continue
        counts[str(node.get("type", "unknown"))] += 1
        counts.update(_count_node_types(node.get("children", [])))
    return counts


def load_document(document_path: str, projection: str | None = None) -> dict[str, Any]:
    """Summarize a ``.forge.json`` on disk without returning the full document.

    With no ``projection``, returns a lightweight metadata summary — ``domain``,
    ``name``, ``forgelab_version``, ``node_count`` (total, including nested
    children), and ``nodes_by_type`` — computed straight from the file.

    projection: request a specific context-projection level instead — one of
    ``metadata``, ``topology`` (simplified node list, no geometry coordinates),
    ``geometry`` (full mesh/pad/sketch geometry, no materials/scene/board
    constraints) or ``full`` (everything). The document is validated and the
    stripped fields never leave ForgeLab, so the agent receives only what the
    chosen level keeps. Call ``get_projection_schema`` to see what each level
    includes. A bare filename resolves against ``FORGELAB_OUTPUT_DIR``.
    """
    require_scope("forge:read")
    if projection is not None:
        _check_projection(projection)
        document_model = validate(_read_document_file(document_path))
        return project(document_model, projection)
    data = _read_document_file(document_path)
    counts = _count_node_types(data.get("nodes", []))
    meta = data.get("meta")
    name = meta.get("name") if isinstance(meta, dict) else None
    return {
        "domain": data.get("domain"),
        "name": name,
        "forgelab_version": data.get("forgelab_version"),
        "node_count": sum(counts.values()),
        "nodes_by_type": dict(counts),
    }


def get_projection_schema(domain: str, projection: str) -> dict[str, Any]:
    """Describe what a projection level includes and excludes for a domain.

    Returns ``{"domain", "projection", "description", "includes", "excludes",
    "levels"}`` so an agent can choose which projection to request from
    ``load_document`` / ``validate_document`` / ``export_document`` without
    trial and error. ``domain`` is ``hardware``, ``threed`` or ``mechanical``;
    ``projection`` is ``metadata``, ``topology``, ``geometry`` or ``full``.
    """
    require_scope("forge:read")
    return projection_schema(domain, projection)


def _touches_nodes(operation: Any) -> bool:
    """True if a patch operation's target (path or move/copy source) is under /nodes."""
    if not isinstance(operation, dict):
        return False
    for key in ("path", "from"):
        value = operation.get(key)
        if isinstance(value, str) and (value == "/nodes" or value.startswith("/nodes/")):
            return True
    return False


def patch_document(
    document_path: str,
    patch: list[dict[str, Any]],
    output_path: str | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Apply an RFC 6902 JSON Patch to a ``.forge.json`` on disk, in one step.

    Mutate an existing document without re-emitting the whole thing: read it,
    apply the patch, optionally validate, and write — so the full JSON never
    re-enters your context window.

    Args:
        document_path: path to the existing ``.forge.json`` (a bare filename
            resolves against ``FORGELAB_OUTPUT_DIR``).
        patch: an RFC 6902 JSON Patch array — a list of ``{"op", "path", ...}``
            operations. Supports add, remove, replace, move, copy and test, e.g.
            ``[{"op": "replace", "path": "/nodes/0/props/value", "value": "10k"}]``.
        output_path: where to write the result; if omitted, overwrites
            ``document_path`` in place.
        validate: when true (default), validate the patched document against the
            ForgeLab schema before writing — if it is invalid, nothing is written
            and the result reports ``valid: false`` with an ``error``.

    Returns:
        ``{"patched": bool, "document_path": str, "nodes_changed": int, "valid":
        bool|None}``. ``nodes_changed`` counts the patch operations that touched
        nodes (not metadata). ``valid`` is the schema result when ``validate`` is
        true, else ``None``. On a validation failure ``patched`` is false and an
        ``error`` is included. A malformed patch raises an error.
    """
    require_scope("forge:export")
    source = _read_document_file(document_path)
    try:
        patched = apply_patch(source, patch)
    except PatchError as exc:
        raise ValueError(f"patch failed: {exc}") from exc
    nodes_changed = sum(1 for op in patch if _touches_nodes(op)) if isinstance(patch, list) else 0
    target = _resolve_path(output_path if output_path is not None else document_path)
    if validate:
        try:
            _core_validate(patched)
        except Exception as exc:
            return {
                "patched": False,
                "document_path": str(target),
                "nodes_changed": nodes_changed,
                "valid": False,
                "error": str(exc),
            }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not write {str(target)!r}: {exc}") from exc
    return {
        "patched": True,
        "document_path": str(target),
        "nodes_changed": nodes_changed,
        "valid": True if validate else None,
    }


def diff_documents(document_path_a: str, document_path_b: str) -> list[dict[str, Any]]:
    """Return the RFC 6902 patch that transforms document A into document B.

    Reads both ``.forge.json`` files (bare filenames resolve against
    ``FORGELAB_OUTPUT_DIR``) and returns a JSON Patch array — a list of
    ``{"op", "path", ...}`` operations — so an agent can inspect what changed
    between two versions of a design without loading either document fully.
    Applying the returned patch to A yields B.
    """
    require_scope("forge:read")
    a = _read_document_file(document_path_a)
    b = _read_document_file(document_path_b)
    return diff(a, b)


# --------------------------------------------------------------------------- #
# Deterministic calculation tools (forgelab.calc). Read/compute only — no auth
# scope beyond forge:read — so agents offload geometry and electrical math
# instead of computing it inline and making arithmetic mistakes.
# --------------------------------------------------------------------------- #
def calculate_pad_positions(
    footprint_type: str,
    pitch: float,
    count: int,
    dual_row: bool = True,
    row_spacing: float | None = None,
) -> list[dict[str, object]]:
    """Pad offsets for a standard IC package, as ``{"number", "at": [x, y]}`` (mm).

    Lay out the pads of a footprint instead of computing offsets by hand.
    ``footprint_type`` is ``"DIP"``, ``"SOIC"``, ``"SOP"`` (dual-row) or ``"QFP"``
    (quad). ``pitch`` is pin-to-pin spacing in mm; ``count`` the total pad count
    (even for dual-row, divisible by 4 for QFP). ``dual_row=False`` gives a single
    in-line row (ignored for QFP); ``row_spacing`` overrides the per-family default
    distance between rows. Pin 1 is top-left, numbering counter-clockwise. Drop
    each ``at`` straight into a hardware ``Pad``.
    """
    require_scope("forge:read")
    return _calc_pad_positions(footprint_type, pitch, count, dual_row, row_spacing)


def calculate_polygon(sides: int, radius: float, center: list[float] | None = None) -> list[float]:
    """Vertices of a regular polygon as a flat ``[x, y, x, y, ...]`` list.

    For tower/prism cross-sections, octagonal pads, and circular approximations.
    ``sides`` >= 3, ``radius`` is the circumradius, ``center`` is an optional
    ``[x, y]`` (default origin). The first vertex is on the +X axis, proceeding
    counter-clockwise. Returns ``2 * sides`` floats.
    """
    require_scope("forge:read")
    return _calc_polygon(sides, radius, center)


def calculate_rotation_matrix(angle_deg: float, axis: str = "y") -> list[float]:
    """Rotation quaternion ``[x, y, z, w]`` for the threed transform rotation field.

    Returns a unit quaternion (not a matrix) in glTF's ``[x, y, z, w]`` order so
    agents stop guessing quaternion values. ``angle_deg`` is degrees; ``axis`` is
    ``"x"``, ``"y"`` or ``"z"`` (default ``"y"``, the up axis in the Y-up threed
    domain).
    """
    require_scope("forge:read")
    return _calc_rotation_matrix(angle_deg, axis)


def calculate_trace_width(
    current_amps: float,
    copper_weight_oz: float = 1.0,
    temp_rise_c: float = 10.0,
    external: bool = True,
) -> float:
    """Recommended PCB trace width in mm via IPC-2221, in one call.

    ``current_amps`` is the continuous current; ``copper_weight_oz`` the copper
    thickness in oz/ft^2 (default 1.0); ``temp_rise_c`` the allowed temperature
    rise in C (default 10.0); ``external=False`` for an inner-layer trace (wider).
    Returns the minimum width in millimetres.
    """
    require_scope("forge:read")
    return _calc_trace_width(current_amps, copper_weight_oz, temp_rise_c, external)


def calculate_board_layout(
    component_count: int,
    board_width: float,
    board_height: float,
    margin: float = 2.0,
    reference_prefix: str = "U",
) -> list[dict[str, object]]:
    """Suggest grid placements as ``{"reference", "at": [x, y]}`` (mm).

    Spreads ``component_count`` components over a margin-aware grid inside a
    ``board_width`` x ``board_height`` outline (origin at the lower-left corner),
    so an agent does not plan coordinates by hand. ``margin`` is the edge keep-out
    (default 2.0 mm); ``reference_prefix`` names the parts (``"U"`` -> U1, U2, ...).
    """
    require_scope("forge:read")
    return _calc_board_layout(component_count, board_width, board_height, margin, reference_prefix)


def _agent_extra_installed() -> bool:
    """True if the Anthropic SDK (the ``agent`` extra) is importable."""
    try:
        import anthropic  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _generation_availability() -> tuple[bool, str | None]:
    """Whether ``generate_document`` can run, and if not, why.

    Generation needs both ``ANTHROPIC_API_KEY`` set on the server and the
    ``agent`` extra installed. Returns ``(available, reason)`` where ``reason``
    is ``None`` when available.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY is not set on the server"
    if not _agent_extra_installed():
        return False, 'the agent extra is not installed (pip install "forgelab[agent]")'
    return True, None


def generation_status() -> dict[str, Any]:
    """Report whether ``generate_document`` is currently usable on this server.

    Call this before ``generate_document`` to avoid a wasted round trip: when
    generation is unavailable (no API key, or the agent extra is not installed),
    skip ``generate_document`` and build the document yourself against the schema
    instead. Returns ``{"available": bool}``; when unavailable, also ``"reason"``
    and an ``"alternative"`` describing how to proceed without generation.
    """
    require_scope("forge:read")
    available, reason = _generation_availability()
    if available:
        return {"available": True}
    return {
        "available": False,
        "reason": reason,
        "alternative": (
            "Build the document yourself: call get_domain_schema and get_prompt "
            "for the domain, construct the complete document in one pass, then "
            "call validate_document once."
        ),
    }


def export_document(
    document: dict[str, Any] | None = None,
    tool: str = "",
    output_path: str | None = None,
    document_path: str | None = None,
    projection: str | None = None,
) -> dict[str, Any]:
    """Export a ForgeLab document to a format tool's native file.

    Provide the document either inline as ``document`` or, to keep large JSON out
    of your context window, as ``document_path`` pointing at a ``.forge.json`` on
    disk (a bare filename resolves against ``FORGELAB_OUTPUT_DIR``). Exactly one
    of the two must be given. ``tool`` is required.

    Without ``output_path``, returns the file inline:
    {"tool", "encoding": "utf-8"|"base64", "content": <str>}.

    With ``output_path``, writes the file to disk and returns
    {"tool", "path", "bytes_written"} so another tool (e.g. a KiCad or Blender
    MCP server) can open it directly.

    output_path: Prefer a bare filename (e.g. "castle.gltf") so the file is
    written to the configured FORGELAB_OUTPUT_DIR. Only pass an absolute path if
    you need to write somewhere else. A bare filename is written into
    ``FORGELAB_OUTPUT_DIR`` when set, else the current working directory.

    projection: when set (e.g. ``"topology"``), the export is still performed in
    full — ForgeLab loads the whole document and writes the native file — but the
    response carries only ``{"tool", "exported": true, ...path/bytes..., "projection":
    <projected document>}`` at that level instead of the export bytes or the full
    document. Use it with ``document_path`` + ``output_path`` to get a lightweight
    confirmation rather than a large response.
    """
    require_scope("forge:export")
    if not tool:
        raise ValueError("tool is required")
    if projection is not None:
        _check_projection(projection)
    source = _document_source(document, document_path)
    try:
        doc = validate(source)
    except Exception as exc:
        raise ValueError(f"invalid document: {exc}") from exc
    try:
        exporter = _registry.get_exporter(tool)
    except UnknownToolError as exc:
        raise ValueError(str(exc)) from exc
    try:
        data = exporter().from_ir(doc)
    except NotImplementedError as exc:
        raise ValueError(f"export not implemented for {tool!r}: {exc}") from exc
    except ValidationError as exc:
        # The IR validator is lenient about node props; exporters re-validate
        # them strictly against the domain models.
        raise ValueError(f"export failed for {tool!r}: document props are invalid: {exc}") from exc
    except ValueError as exc:
        # Exporters raise ValueError for actionable problems (e.g. a reference
        # that names a node by display name instead of its id).
        raise ValueError(f"export failed for {tool!r}: {exc}") from exc
    written: dict[str, Any] | None = None
    if output_path is not None:
        target = _resolve_path(output_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            raise ValueError(f"could not write {str(target)!r}: {exc}") from exc
        written = {"path": str(target), "bytes_written": len(data)}
    if projection is not None:
        # The full export ran; return a lightweight projected view, not the bytes.
        response: dict[str, Any] = {"tool": tool, "exported": True}
        if written is not None:
            response.update(written)
        response["projection"] = project(doc, projection)
        return response
    if written is not None:
        return {"tool": tool, **written}
    return {"tool": tool, **encode_bytes(data)}


def import_file(tool: str, content: str, encoding: str = "utf-8") -> dict[str, Any]:
    """Import a format tool's native file into a ForgeLab document (as a dict)."""
    require_scope("forge:export")
    try:
        importer = _registry.get_importer(tool)
    except UnknownToolError as exc:
        raise ValueError(str(exc)) from exc
    source = decode_content(content, encoding)
    document = importer().to_ir(source)
    return document.model_dump(mode="json")


def _make_agent(model: str) -> ForgeAgent:
    """Construct a ForgeAgent. Indirection so tests can inject a fake agent."""
    return ForgeAgent(model=model)


def generate_document(prompt: str, domain: str, model: str = "claude-opus-4-8") -> dict[str, Any]:
    """Generate a validated ForgeLab document from a natural-language prompt."""
    require_scope("forge:generate")
    if domain not in DOMAIN_VOCAB:
        raise ValueError(f"unknown domain: {domain!r}; valid domains: {sorted(DOMAIN_VOCAB)}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("generation unavailable: ANTHROPIC_API_KEY is not set on the server")
    try:
        agent = _make_agent(model)
    except ImportError as exc:
        raise ValueError(
            'generation unavailable: install the agent extra (pip install "forgelab[agent]")'
        ) from exc
    document = agent.design(prompt, domain=domain)
    return document.model_dump(mode="json")
