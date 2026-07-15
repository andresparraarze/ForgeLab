"""ForgeLab MCP tool callables.

Plain functions wrapping the core compiler, registry, and AI SDK. ``server.py``
registers them with FastMCP. Each enforces its scope via ``require_scope`` (a
no-op over the unauthenticated stdio transport).
"""

from __future__ import annotations

import base64
import csv
import importlib.util
import io
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from forgelab import history as _history
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
from forgelab.components import get_component as _get_component
from forgelab.components import list_components as _list_components
from forgelab.core import LLMOutputError, UnknownToolError, default_registry, validate
from forgelab.core import validate as _core_validate
from forgelab.layout import (
    DEFAULT_GRID_RESOLUTION,
    DEFAULT_KEEPOUT,
    DEFAULT_LARGE_INSET,
    PlacementError,
    RoutingError,
    place_components,
    route_document,
)
from forgelab.mcp.auth_bridge import require_scope
from forgelab.mcp.content import decode_content, encode_bytes
from forgelab.patch import PatchError, apply_patch, diff
from forgelab.project import (
    PROJECT_EXTENSION,
    Project,
    check_constraints,
    default_tool_for_domain,
    dump_project,
    extension_for_tool,
    infer_shared,
    load_project_file,
)
from forgelab.projection import PROJECTION_LEVELS, project, projection_schema
from forgelab.sdk import DOMAIN_VOCAB, ForgeAgent, domain_schema, few_shot, system_prompt
from forgelab.sdk.validation import _extract_json
from forgelab.sync import document_hash, read_native_hash, tool_for_path
from forgelab.validation import (
    check_fab_rules,
    check_hardware,
    check_mechanical,
    fab_profiles,
)
from forgelab.validation import (
    check_gerber_completeness as _check_gerber_completeness,
)

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

    Domain sanity checks run after the structural check. Mechanical documents get
    geometry/feature checks (sketch closure, positive pad length, pocket depth
    bounds, positive circle radius, body-reference consistency); hardware
    documents get engineering-rule checks (LED series resistor, power-net
    decoupling, capacitor voltage rating, undefined net references, board
    outline). Fatal problems become ``error`` (and ``valid`` is False); non-fatal
    ones are returned in ``warnings`` without affecting ``valid``. The threed
    domain has no extra checks.

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
    # fatal (valid=False); warnings are surfaced but non-fatal. Each check gates
    # on its own domain and returns ([], []) otherwise, so both run safely.
    errors, warnings = check_mechanical(document_model)
    h_errors, h_warnings = check_hardware(document_model)
    errors += h_errors
    warnings += h_warnings
    # Fabrication rules are advisory here: a hardware board with design_rules is
    # checked against the default fab (jlcpcb) and any violations are surfaced as
    # warnings, since the user may be targeting a different fab. Use the
    # check_fabrication tool to validate against a specific fab.
    warnings += _fab_warnings(document_model)
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
    """List registered format tools and their import/export availability.

    Includes the synthetic ``bom`` output (export-only): a bill of materials
    extracted from a hardware document by ``generate_bom``, not a registered
    importer/exporter.
    """
    require_scope("forge:read")
    formats = _registry.tool_names()
    formats["bom"] = {"import": False, "export": True}
    return formats


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
    native_path: str | None = None,
    force: bool = False,
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
        native_path: optional path to the native file this document was exported
            to. When given, ForgeLab runs ``verify_sync`` first and refuses to
            patch a document whose native file has drifted out of sync (nothing
            is written; the result reports ``patched: false`` with the sync
            details), unless ``force`` is also true.
        force: skip the ``native_path`` sync check and patch anyway.

    Returns:
        ``{"patched": bool, "document_path": str, "nodes_changed": int, "valid":
        bool|None}``. ``nodes_changed`` counts the patch operations that touched
        nodes (not metadata). ``valid`` is the schema result when ``validate`` is
        true, else ``None``. On a validation failure ``patched`` is false and an
        ``error`` is included. A malformed patch raises an error.
    """
    require_scope("forge:export")
    if native_path is not None and not force:
        status = _sync_status(document_path, native_path)
        if not status["in_sync"]:
            return {
                "patched": False,
                "error": (
                    "native file is out of sync with the document; refusing to "
                    "patch. Pass force=true to override, or run import_file to "
                    "rebuild the document from the native file first."
                ),
                **status,
            }
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
    _history.record(
        target,
        {
            "tool": "patch_document",
            "document_path": str(target),
            "operations": len(patch) if isinstance(patch, list) else 0,
            "nodes_changed": nodes_changed,
        },
    )
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


def _read_native_file(native_path: str) -> tuple[Path, bytes]:
    target = _resolve_path(native_path)
    try:
        return target, target.read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read native file {str(target)!r}: {exc}") from exc


def _sync_status(document_path: str, native_path: str) -> dict[str, Any]:
    """Compare a native file's embedded hash with its source document's hash."""
    native_target, content = _read_native_file(native_path)
    tool = tool_for_path(native_path)
    if tool is None:
        raise ValueError(
            f"cannot determine the format tool from {native_path!r}; "
            "expected a .kicad_pcb, .gltf or .FCStd file"
        )
    native_hash = read_native_hash(tool, content)
    raw = _read_document_file(document_path)
    try:
        model = _core_validate(raw)
    except Exception as exc:
        doc_target = _resolve_path(document_path)
        raise ValueError(f"invalid document {str(doc_target)!r}: {exc}") from exc
    doc_hash = document_hash(model.model_dump(mode="json"))
    in_sync = native_hash is not None and native_hash == doc_hash
    result: dict[str, Any] = {
        "in_sync": in_sync,
        "document_hash": doc_hash,
        "native_hash": native_hash,
        "native_path": str(native_target),
        "document_path": str(_resolve_path(document_path)),
    }
    if not in_sync:
        result["recommendation"] = (
            "Run import_file to rebuild the ForgeLab document from the native file before patching"
        )
    return result


def verify_sync(document_path: str, native_path: str) -> dict[str, Any]:
    """Check whether a native file is still in sync with its source document.

    On export ForgeLab embeds a hash of the source document into the native file
    (a KiCad board ``property``, glTF ``asset.extras``, or a ``Hash`` attribute on
    the FreeCAD sidecar). This reads that hash and compares it with the hash of
    the current ``.forge.json`` on disk, so an agent can tell — before issuing
    patch operations — whether the two have drifted apart.

    Args:
        document_path: the ``.forge.json`` (a bare filename resolves against
            ``FORGELAB_OUTPUT_DIR``).
        native_path: the exported native file (``.kicad_pcb``, ``.gltf`` or
            ``.FCStd``); the tool is inferred from the extension.

    Returns:
        ``{"in_sync": bool, "document_hash": str, "native_hash": str|None,
        "native_path": str, "document_path": str}``. When out of sync, a
        ``recommendation`` field is added. ``native_hash`` is ``None`` when the
        file carries no embedded hash (treated as out of sync).
    """
    require_scope("forge:read")
    return _sync_status(document_path, native_path)


# --------------------------------------------------------------------------- #
# Bill of materials: extract a grouped parts list from a hardware document.
# --------------------------------------------------------------------------- #
def _component_nets(props: dict[str, Any]) -> list[str]:
    """Unique, non-empty net names across a component's pads, in first-seen order."""
    nets: list[str] = []
    pads = props.get("pads")
    if isinstance(pads, list):
        for pad in pads:
            if not isinstance(pad, dict):
                continue
            net = pad.get("net")
            if isinstance(net, str) and net and net not in nets:
                nets.append(net)
    return nets


def _collect_bom(document: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """Group component nodes by (value, footprint); return (total, ordered groups)."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    total = 0
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return 0, []
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "component":
            continue
        raw_props = node.get("props")
        props: dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
        reference = str(props.get("reference") or node.get("id") or "")
        value = str(props.get("value", ""))
        footprint = str(props.get("footprint", ""))
        total += 1
        key = (value, footprint)
        group = groups.get(key)
        if group is None:
            group = {
                "quantity": 0,
                "references": [],
                "value": value,
                "footprint": footprint,
                "nets": [],
            }
            groups[key] = group
            order.append(key)
        group["quantity"] += 1
        if reference:
            group["references"].append(reference)
        for net in _component_nets(props):
            if net not in group["nets"]:
                group["nets"].append(net)
    return total, [groups[key] for key in order]


def _bom_csv(groups: list[dict[str, Any]]) -> str:
    """Render BOM groups as CSV with a Quantity/References/Value/Footprint header."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Quantity", "References", "Value", "Footprint"])
    for group in groups:
        writer.writerow(
            [
                group["quantity"],
                ",".join(group["references"]),
                group["value"],
                group["footprint"],
            ]
        )
    return buffer.getvalue()


def generate_bom(document_path: str, format: str = "json") -> dict[str, Any] | str:
    """Extract a bill of materials from a hardware ``.forge.json`` on disk.

    Reads the document (a bare filename resolves against ``FORGELAB_OUTPUT_DIR``),
    walks its ``component`` nodes, and groups identical parts (same ``value`` +
    ``footprint``), summing quantities. For each component it pulls the reference,
    value, footprint, and the unique net names connected to its pads.

    Args:
        document_path: the hardware ``.forge.json`` to read.
        format: ``"json"`` (default) or ``"csv"``.

    Returns:
        For ``"json"``: ``{"total_components", "unique_parts", "bom"}`` where each
        ``bom`` entry is ``{"quantity", "reference" (comma-joined refs), "value",
        "footprint", "nets"}``. For ``"csv"``: a CSV string with the header
        ``Quantity, References, Value, Footprint``.
    """
    require_scope("forge:read")
    fmt = format.lower()
    if fmt not in ("json", "csv"):
        raise ValueError(f"unknown format {format!r}; expected 'json' or 'csv'")
    raw = _read_document_file(document_path)
    domain = raw.get("domain")
    if domain != "hardware":
        raise ValueError(f"generate_bom requires a hardware document; got domain {domain!r}")
    total, groups = _collect_bom(raw)
    if fmt == "csv":
        return _bom_csv(groups)
    bom = [
        {
            "quantity": group["quantity"],
            "reference": ",".join(group["references"]),
            "value": group["value"],
            "footprint": group["footprint"],
            "nets": group["nets"],
        }
        for group in groups
    ]
    return {"total_components": total, "unique_parts": len(groups), "bom": bom}


# --------------------------------------------------------------------------- #
# Component library: pre-built footprint + pad-geometry definitions an agent can
# drop into a hardware document instead of inventing footprints.
# --------------------------------------------------------------------------- #
def list_components() -> dict[str, list[str]]:
    """List every pre-built component, grouped by category.

    Returns a mapping of category name (``"Microcontrollers"``, ``"Regulators"``,
    ``"USB"``, ``"Passives"``, ``"Connectors"``) to the component names in it.
    Pass a name to ``get_component`` for its full definition.
    """
    require_scope("forge:read")
    return _list_components()


def get_component(name: str) -> dict[str, Any]:
    """Return a pre-built component definition ready for a hardware document.

    Looks ``name`` up in the component library (case-insensitive) and returns
    ``{"name", "category", "value", "footprint", "description", "pads"}``, where
    ``pads`` is a list of ``{"number", "at": [x, y]}`` with datasheet-accurate
    positions (TQFP/QFP parts use the same geometry as ``calculate_pad_positions``).

    The definition is footprint-level: merge it with a ``reference``, a ``layer``
    (e.g. ``"F.Cu"``) and a board ``at`` to form a hardware ``component`` node.
    Call ``list_components`` for the available names.
    """
    require_scope("forge:read")
    try:
        return _get_component(name)
    except KeyError as exc:
        available = sorted(n for names in _list_components().values() for n in names)
        raise ValueError(f"unknown component {name!r}; available: {', '.join(available)}") from exc


# --------------------------------------------------------------------------- #
# ForgeLab projects: a .forge.project container ties multiple domain documents
# together with shared dimensions (a single source of truth) and informational
# cross-domain constraints. The project file is not itself a domain document.
# --------------------------------------------------------------------------- #
def _project_doc_key(path_str: str) -> str:
    """Derive a short document key from a file path (strip the ForgeLab suffix)."""
    name = Path(path_str).name
    for suffix in (".forge.json", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _resolve_project_doc(project_dir: Path, doc_path: str) -> Path:
    """Resolve a document path stored in a project relative to the project file."""
    path = Path(doc_path)
    return path if path.is_absolute() else project_dir / path


def create_project(
    name: str,
    description: str = "",
    document_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Create a ForgeLab project file linking several domain documents.

    A project is a ``.forge.project`` JSON file (not a domain document) that ties
    documents together with a flat ``shared`` dimension table — a single source of
    truth every linked document can be checked against (e.g. a board outline width
    informing an enclosure's inner width).

    Args:
        name: the project name; the file is written as ``<name>.forge.project``
            into ``FORGELAB_OUTPUT_DIR`` (or the cwd).
        description: an optional human description.
        document_paths: optional existing ``.forge.json`` paths to link. Each is
            keyed by its base filename. Shared dimensions are inferred
            automatically from any hardware document (``board_width`` and
            ``board_height`` from the board outline's bounding box).

    Returns ``{"project_path", "name", "documents", "shared"}``.
    """
    require_scope("forge:read")
    if not name:
        raise ValueError("name is required")
    documents: dict[str, str] = {}
    shared: dict[str, float] = {}
    for raw_path in document_paths or []:
        key = _project_doc_key(raw_path)
        documents[key] = raw_path
        try:
            doc = _read_document_file(raw_path)
        except ValueError as exc:
            raise ValueError(f"could not add document {raw_path!r}: {exc}") from exc
        shared.update(infer_shared(doc))
    project_model = Project(
        name=name,
        description=description or None,
        documents=documents,
        shared=shared,
    )
    filename = name if name.endswith(PROJECT_EXTENSION) else f"{name}{PROJECT_EXTENSION}"
    target = _resolve_path(filename)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dump_project(project_model), encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not write project {str(target)!r}: {exc}") from exc
    return {
        "project_path": str(target),
        "name": project_model.name,
        "documents": dict(project_model.documents),
        "shared": dict(project_model.shared),
    }


def load_project(project_path: str) -> dict[str, Any]:
    """Load a project file and summarize it without returning document contents.

    Reads a ``.forge.project`` and returns its metadata, shared dimensions, and a
    per-document summary (key, resolved path, domain, node count, validation
    status). Document paths resolve relative to the project file. The full
    document JSON is never returned, keeping the response small.

    Returns ``{"project_path", "name", "description", "shared", "documents",
    "constraint_count"}``.
    """
    require_scope("forge:read")
    target = _resolve_path(project_path)
    project_model = load_project_file(target)
    project_dir = target.parent
    summaries: list[dict[str, Any]] = []
    for key, doc_path in project_model.documents.items():
        resolved = _resolve_project_doc(project_dir, doc_path)
        summary: dict[str, Any] = {"key": key, "path": str(resolved)}
        try:
            raw = json.loads(resolved.read_text(encoding="utf-8"))
        except OSError as exc:
            summary.update({"domain": None, "node_count": 0, "valid": False, "error": str(exc)})
            summaries.append(summary)
            continue
        except json.JSONDecodeError as exc:
            summary.update(
                {"domain": None, "node_count": 0, "valid": False, "error": f"invalid JSON: {exc}"}
            )
            summaries.append(summary)
            continue
        summary["domain"] = raw.get("domain") if isinstance(raw, dict) else None
        nodes = raw.get("nodes") if isinstance(raw, dict) else None
        summary["node_count"] = sum(_count_node_types(nodes).values())
        try:
            _core_validate(raw)
            summary["valid"] = True
        except Exception as exc:
            summary["valid"] = False
            summary["error"] = str(exc)
        summaries.append(summary)
    return {
        "project_path": str(target),
        "name": project_model.name,
        "description": project_model.description,
        "shared": dict(project_model.shared),
        "documents": summaries,
        "constraint_count": len(project_model.constraints),
    }


def update_project(
    project_path: str,
    shared: dict[str, float],
    revalidate: bool = False,
) -> dict[str, Any]:
    """Update a project's shared dimension values, optionally re-checking docs.

    Merges ``shared`` into the project's dimension table (overwriting matching
    keys, adding new ones) and writes the file back. With ``revalidate=True``,
    every linked document is re-validated and all constraints are re-checked
    against the new dimensions; the report is informational and never blocks.

    Returns ``{"project_path", "shared", "updated"}`` and, when revalidating,
    ``"validation"``, ``"constraints"`` and ``"violations"`` (the unsatisfied
    subset).
    """
    require_scope("forge:export")
    if not isinstance(shared, dict) or not shared:
        raise ValueError("shared must be a non-empty dict of dimension name -> value")
    target = _resolve_path(project_path)
    project_model = load_project_file(target)
    updated: list[str] = []
    for dim, value in shared.items():
        try:
            project_model.shared[dim] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"shared value for {dim!r} must be numeric: {exc}") from exc
        updated.append(dim)
    try:
        target.write_text(dump_project(project_model), encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not write project {str(target)!r}: {exc}") from exc
    _history.record(
        target,
        {
            "tool": "update_project",
            "project_path": str(target),
            "updated": sorted(updated),
        },
    )
    result: dict[str, Any] = {
        "project_path": str(target),
        "shared": dict(project_model.shared),
        "updated": sorted(updated),
    }
    if revalidate:
        project_dir = target.parent
        loaded: dict[str, dict[str, Any]] = {}
        validation: list[dict[str, Any]] = []
        for key, doc_path in project_model.documents.items():
            resolved = _resolve_project_doc(project_dir, doc_path)
            try:
                raw = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                validation.append({"key": key, "valid": False, "error": str(exc)})
                continue
            loaded[key] = raw
            try:
                _core_validate(raw)
                validation.append({"key": key, "valid": True})
            except Exception as exc:
                validation.append({"key": key, "valid": False, "error": str(exc)})
        reports = check_constraints(project_model, loaded)
        result["validation"] = validation
        result["constraints"] = reports
        result["violations"] = [r for r in reports if not r["satisfied"]]
    return result


def export_project(
    project_path: str,
    tools: dict[str, str] | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Export every document in a project to its native format in one call.

    Each document is written as ``<key><ext>`` (e.g. ``board.kicad_pcb``) into
    ``output_dir`` (default: the project file's directory). The export tool per
    document defaults to its domain's natural target (hardware->kicad,
    mechanical->freecad, threed->gltf); override any with ``tools``, e.g.
    ``{"board": "kicad", "enclosure": "freecad", "render": "blender_script"}``.

    Returns ``{"project_path", "name", "output_dir", "exported", "exported_count",
    "constraints", "violations"}``. ``exported`` lists one entry per document with
    its tool, path and bytes (or an ``error``); a failure on one document does not
    stop the others. Constraint violations are reported but never block.
    """
    require_scope("forge:export")
    target = _resolve_path(project_path)
    project_model = load_project_file(target)
    project_dir = target.parent
    overrides = tools or {}
    out_base = _resolve_path(output_dir) if output_dir else project_dir
    try:
        out_base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"could not create output dir {str(out_base)!r}: {exc}") from exc

    exported: list[dict[str, Any]] = []
    loaded: dict[str, dict[str, Any]] = {}
    for key, doc_path in project_model.documents.items():
        resolved = _resolve_project_doc(project_dir, doc_path)
        entry: dict[str, Any] = {"document": key}
        try:
            raw = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            entry.update({"exported": False, "error": f"could not read document: {exc}"})
            exported.append(entry)
            continue
        loaded[key] = raw
        try:
            doc = validate(raw)
        except Exception as exc:
            entry.update({"exported": False, "error": f"invalid document: {exc}"})
            exported.append(entry)
            continue
        domain = raw.get("domain") if isinstance(raw, dict) else None
        tool = overrides.get(key) or default_tool_for_domain(str(domain))
        if not tool:
            entry.update(
                {
                    "exported": False,
                    "error": (
                        f"no default export tool for domain {domain!r}; "
                        f"pass tools={{{key!r}: <tool>}}"
                    ),
                }
            )
            exported.append(entry)
            continue
        entry["tool"] = tool
        try:
            exporter = _registry.get_exporter(tool)
        except UnknownToolError as exc:
            entry.update({"exported": False, "error": str(exc)})
            exported.append(entry)
            continue
        try:
            data = exporter().from_ir(doc)
        except (NotImplementedError, ValidationError, ValueError) as exc:
            entry.update({"exported": False, "error": f"export failed: {exc}"})
            exported.append(entry)
            continue
        out_path = out_base / f"{key}{extension_for_tool(tool)}"
        try:
            out_path.write_bytes(data)
        except OSError as exc:
            entry.update({"exported": False, "error": f"could not write {str(out_path)!r}: {exc}"})
            exported.append(entry)
            continue
        entry.update({"exported": True, "path": str(out_path), "bytes_written": len(data)})
        exported.append(entry)

    reports = check_constraints(project_model, loaded)
    exported_ok = [e for e in exported if e.get("exported")]
    if exported_ok:
        _history.record(
            target,
            {
                "tool": "export_project",
                "project_path": str(target),
                "documents": [e["document"] for e in exported_ok],
                "tools": sorted({e["tool"] for e in exported_ok if e.get("tool")}),
            },
        )
    return {
        "project_path": str(target),
        "name": project_model.name,
        "output_dir": str(out_base),
        "exported": exported,
        "exported_count": len(exported_ok),
        "constraints": reports,
        "violations": [r for r in reports if not r["satisfied"]],
    }


# --------------------------------------------------------------------------- #
# Design history: a .forge.history sidecar records every write so agents and
# users can see what changed between versions.
# --------------------------------------------------------------------------- #
def _history_summary(entry: dict[str, Any]) -> str:
    """A one-line, human-readable summary of a history entry."""
    tool = entry.get("tool", "?")
    if tool == "patch_document":
        return (
            f"patched {entry.get('document_path')}: "
            f"{entry.get('operations', 0)} op(s), "
            f"{entry.get('nodes_changed', 0)} node(s) changed"
        )
    if tool == "export_document":
        return (
            f"exported {entry.get('document_path')} -> {entry.get('output_tool')} "
            f"({entry.get('bytes_written', 0)} bytes) at {entry.get('output_path')}"
        )
    if tool == "export_project":
        docs = entry.get("documents") or []
        tools_used = entry.get("tools") or []
        return (
            f"exported project {entry.get('project_path')}: "
            f"{len(docs)} document(s) via {', '.join(tools_used) or 'n/a'}"
        )
    if tool == "update_project":
        keys = entry.get("updated") or []
        return f"updated shared dims on {entry.get('project_path')}: {', '.join(keys) or 'none'}"
    return tool


def get_history(path: str) -> list[dict[str, Any]]:
    """Return the recent change history for a document or project.

    Finds the ``.forge.history`` file beside ``path`` (a bare filename resolves
    against ``FORGELAB_OUTPUT_DIR``) and returns the last 20 entries, newest last,
    each as ``{"timestamp", "tool", "summary"}``. Returns an empty list when no
    history file exists yet.
    """
    require_scope("forge:read")
    target = _resolve_path(path)
    entries = _history.read_history(target)
    return [
        {
            "timestamp": entry.get("timestamp"),
            "tool": entry.get("tool"),
            "summary": _history_summary(entry),
        }
        for entry in entries[-20:]
    ]


def get_project_summary(project_path: str) -> dict[str, Any]:
    """Return a quick, human-readable status of a project without loading docs.

    Reads the ``.forge.project`` file and its sibling ``.forge.history`` and
    returns the project name, description, linked documents, shared dimensions,
    last-modified timestamp, export count and total change count — a status check
    that never opens any document. A bare filename resolves against
    ``FORGELAB_OUTPUT_DIR``.

    Returns ``{"name", "description", "documents", "shared", "last_modified",
    "export_count", "total_changes", "summary"}``.
    """
    require_scope("forge:read")
    target = _resolve_path(project_path)
    project_model = load_project_file(target)
    entries = _history.read_history(target)
    export_count = sum(1 for e in entries if e.get("tool") in ("export_document", "export_project"))
    if entries:
        last_modified = entries[-1].get("timestamp")
    else:
        try:
            mtime = target.stat().st_mtime
            last_modified = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        except OSError:
            last_modified = None

    documents = dict(project_model.documents)
    shared = dict(project_model.shared)
    dims = ", ".join(f"{k}={v}" for k, v in shared.items()) or "none"
    summary = (
        f"Project {project_model.name!r}: {len(documents)} document(s) "
        f"({', '.join(documents) or 'none'}); shared dims: {dims}; "
        f"{export_count} export(s), {len(entries)} total change(s); "
        f"last modified {last_modified or 'never'}"
    )
    return {
        "name": project_model.name,
        "description": project_model.description,
        "documents": documents,
        "shared": shared,
        "last_modified": last_modified,
        "export_count": export_count,
        "total_changes": len(entries),
        "summary": summary,
    }


# --------------------------------------------------------------------------- #
# Fabrication rule checks: validate a hardware design against a PCB fab's limits.
# --------------------------------------------------------------------------- #
_DEFAULT_FAB = "jlcpcb"


def _fab_warnings(document_model: Any) -> list[str]:
    """Default-fab violations as warning strings, only when design_rules exist."""
    if str(document_model.domain) != "hardware":
        return []
    has_rules = any(
        node.type == "board" and isinstance(node.props.get("design_rules"), dict)
        for node in document_model.walk()
    )
    if not has_rules:
        return []
    result = check_fab_rules(document_model, _DEFAULT_FAB)
    return [f"fab({_DEFAULT_FAB}): {e}" for e in result["errors"]]


def check_fabrication(document_path: str, fab: str = _DEFAULT_FAB) -> dict[str, Any]:
    """Check a hardware document against a PCB fab's manufacturing rules.

    Reads the ``.forge.json`` (a bare filename resolves against
    ``FORGELAB_OUTPUT_DIR``) and validates its board ``design_rules``, outline
    and any routed copper against the named fab profile — minimum trace width,
    via diameter, via drill, the board-size envelope, and (when ``track``/``via``
    nodes exist, e.g. after ``route_board``) the actually-routed track widths and
    via geometry plus real geometric clearance between every kind of copper
    pair: track-track, via-pad, via-via, pad-pad, track-pad and track-via
    across nets — the checks that catch genuine short circuits, not just
    declared design rules. Call ``list_fab_profiles`` for the available fab
    names (e.g. ``jlcpcb``, ``pcbway``, ``oshpark``).

    Returns ``{"fab", "passed", "errors", "warnings"}``: ``errors`` are hard rule
    violations the fab would reject; ``warnings`` flag things that could not be
    checked (e.g. no outline to measure). A non-hardware document passes with
    empty lists.
    """
    require_scope("forge:read")
    source = _read_document_file(document_path)
    try:
        model = _core_validate(source)
    except Exception as exc:
        raise ValueError(f"invalid document: {exc}") from exc
    return check_fab_rules(model, fab)


def check_gerber_completeness(document_path: str, fab: str = _DEFAULT_FAB) -> dict[str, Any]:
    """Pre-flight a hardware document before ``export_document(tool='gerber')``.

    Runs the full fab-rule check (design rules, board size, and routed
    track/via geometry) and additionally warns when the board has no routed
    tracks — the Gerbers would carry pads and outline but no copper
    connections, so run ``route_board`` first.

    Returns ``{"ready": bool, "fab", "errors", "warnings"}``. ``ready`` is
    False while any hard fab violation exists; warnings never block. Call
    ``list_fab_profiles`` for the available fab names.
    """
    require_scope("forge:read")
    source = _read_document_file(document_path)
    try:
        model = _core_validate(source)
    except Exception as exc:
        raise ValueError(f"invalid document: {exc}") from exc
    return _check_gerber_completeness(model, fab)


def list_fab_profiles() -> dict[str, dict[str, float]]:
    """List the available PCB fab profiles and their key constraints.

    Returns a mapping of fab name (``jlcpcb``, ``pcbway``, ``oshpark``) to its
    constraint table (minimum trace width/spacing, via diameter/drill, drill
    size, and board-size limits, in millimetres) so an agent can pick a fab and
    see its limits without guessing.
    """
    require_scope("forge:read")
    return fab_profiles()


def auto_place(
    document_path: str,
    output_path: str,
    keepout: float = DEFAULT_KEEPOUT,
    large_component_inset: float = DEFAULT_LARGE_INSET,
) -> dict[str, Any]:
    """Automatically place a hardware document's components on the board.

    Packs all non-locked components inside the board outline with a shelf/row
    algorithm — largest footprint (pad bounding box + ``keepout`` margin, mm)
    first, rows filled left-to-right — guaranteeing zero overlap and zero
    components outside the outline, so agents never hand-guess XY coordinates.
    Components with ``locked: true`` keep their position and are packed around
    as obstacles (e.g. a connector manually placed on a board edge). Placement
    ignores rotation; placed components sit at rotation 0.

    Args:
        document_path: path to the hardware ``.forge.json`` to place (a bare
            filename resolves against ``FORGELAB_OUTPUT_DIR``).
        output_path: where to write the placed document.
        keepout: margin in millimetres added around every component footprint
            (default 0.5).
        large_component_inset: minimum distance in millimetres between a
            large component (footprint over 50mm2 — QFPs/QFNs/modules, not
            passives/headers) and any board edge, preserving routing escape
            channels on all its sides (default 5.0). Smaller parts pack
            flush.

    Returns:
        ``{"placed": true, "document_path", "components_placed",
        "components_locked", "board_utilization"}`` — ``board_utilization`` is
        the packed footprint area as a percentage of the board area, a useful
        signal for whether the board needs to be bigger. When the components
        cannot fit (or the board outline is missing) nothing is written and the
        result is ``{"placed": false, "error": ...}``.
    """
    require_scope("forge:generate")
    data = _read_document_file(document_path)
    try:
        document_model = _core_validate(data)
    except Exception as exc:
        raise ValueError(f"invalid document: {exc}") from exc
    try:
        result = place_components(
            document_model, keepout=keepout, large_component_inset=large_component_inset
        )
    except PlacementError as exc:
        return {"placed": False, "error": str(exc)}

    placements: dict[str, list[float]] = result["placements"]

    def apply(nodes: list[Any]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            placement = placements.get(str(node.get("id", "")))
            if placement is not None:
                props = node.get("props")
                if isinstance(props, dict):
                    props["at"] = placement
            apply(node.get("children") or [])

    apply(data.get("nodes") or [])

    target = _resolve_path(output_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not write {str(target)!r}: {exc}") from exc
    _history.record(
        target,
        {
            "tool": "auto_place",
            "document_path": str(target),
            "components_placed": result["components_placed"],
            "board_utilization": result["board_utilization"],
        },
    )
    return {
        "placed": True,
        "document_path": str(target),
        "components_placed": result["components_placed"],
        "components_locked": result["components_locked"],
        "board_utilization": result["board_utilization"],
    }


def route_board(
    document_path: str,
    output_path: str,
    grid_resolution: float = DEFAULT_GRID_RESOLUTION,
    layers: int = 2,
) -> dict[str, Any]:
    """Autoroute a placed hardware document: turn its netlist into real copper.

    Runs a 2-layer grid-based maze router (Lee's algorithm) over the board:
    each net's pads are connected with ``track`` nodes (plus ``via`` nodes
    where a route changes layer), which the KiCad exporter emits as real
    ``(segment ...)``/``(via ...)`` copper. Copper is modelled physically:
    pads block their real rendered size and vias are placed only where their
    ``via_diameter`` barrel keeps ``clearance`` to every other net's copper —
    nets with no legal path land in ``nets_failed`` instead of getting shorted
    copper. The document must already be placed — run ``auto_place`` first if
    components still overlap. This is a basic router for simple-to-moderate
    boards: nets the maze search cannot connect are returned in
    ``nets_failed`` for manual routing rather than failing the whole
    operation. Re-routing replaces any existing track/via nodes.

    Args:
        document_path: path to the placed hardware ``.forge.json`` (a bare
            filename resolves against ``FORGELAB_OUTPUT_DIR``).
        output_path: where to write the routed document.
        grid_resolution: routing grid cell size in millimetres (default 0.15;
            it divides the default track_width + clearance of 0.45 exactly).
        layers: 1 routes on F.Cu only; 2 (default) adds B.Cu joined by vias.

    Returns:
        ``{"routed": true, "document_path", "nets_routed", "nets_failed":
        [net names], "total_track_length_mm", "vias_used"}``. When the board
        cannot be routed at all (e.g. no outline) nothing is written and the
        result is ``{"routed": false, "error": ...}``.
    """
    require_scope("forge:generate")
    data = _read_document_file(document_path)
    try:
        document_model = _core_validate(data)
    except Exception as exc:
        raise ValueError(f"invalid document: {exc}") from exc
    try:
        result = route_document(document_model, grid_resolution=grid_resolution, layers=layers)
    except RoutingError as exc:
        return {"routed": False, "error": str(exc)}

    nodes = [n for n in (data.get("nodes") or []) if n.get("type") not in ("track", "via")]
    nodes.extend(
        {"id": f"track_{i + 1}", "type": "track", "props": props}
        for i, props in enumerate(result["tracks"])
    )
    nodes.extend(
        {"id": f"via_{i + 1}", "type": "via", "props": props}
        for i, props in enumerate(result["vias"])
    )
    data["nodes"] = nodes

    target = _resolve_path(output_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not write {str(target)!r}: {exc}") from exc
    _history.record(
        target,
        {
            "tool": "route_board",
            "document_path": str(target),
            "nets_routed": len(result["nets_routed"]),
            "nets_failed": result["nets_failed"],
            "total_track_length_mm": result["total_track_length_mm"],
        },
    )
    return {
        "routed": True,
        "document_path": str(target),
        "nets_routed": len(result["nets_routed"]),
        "nets_failed": result["nets_failed"],
        "total_track_length_mm": result["total_track_length_mm"],
        "vias_used": result["vias_used"],
    }


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
    """Report whether the API-backed tools are usable on this server.

    Both ``generate_document`` and ``analyze_image`` need ``ANTHROPIC_API_KEY``
    set on the server and the ``agent`` extra installed. Call this first to avoid
    a wasted round trip: when they are unavailable, skip them and build the
    document yourself against the schema instead.

    Returns ``{"available": bool, "generate_document": bool, "analyze_image":
    bool, "critique_render": bool, "preview_render": bool}``; when the API
    tools are unavailable, also ``"reason"`` and an ``"alternative"``
    describing how to proceed. ``critique_render`` shares the API tools'
    requirements; ``preview_render`` is pure-local and only needs the
    ``preview`` extra (``preview_reason`` says so when it is missing).
    ``available`` mirrors ``generate_document`` for backward compatibility.
    """
    require_scope("forge:read")
    available, reason = _generation_availability()
    preview_ok = _preview_extra_installed()
    status: dict[str, Any] = {
        "available": available,
        "generate_document": available,
        "analyze_image": available,
        "critique_render": available,
        "preview_render": preview_ok,
    }
    if not preview_ok:
        status["preview_reason"] = (
            'the preview extra is not installed (pip install "forgelab[preview]")'
        )
    if not available:
        status["reason"] = reason
        status["alternative"] = (
            "Build the document yourself: call get_domain_schema and get_prompt "
            "for the domain, construct the complete document in one pass, then "
            "call validate_document once."
        )
    return status


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

    Tools include ``kicad`` (hardware), ``freecad`` (mechanical), and for the
    threed domain ``gltf`` (a portable ``.gltf``) or ``blender_script`` (a
    runnable Blender ``.py`` that rebuilds the scene with native objects,
    Principled BSDF materials, recognised primitives, a camera and three-point
    lighting — prefer it over ``gltf`` when the target is Blender). Call
    ``list_formats`` for the full list.

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
        anchor = _resolve_path(document_path) if document_path else target
        _history.record(
            anchor,
            {
                "tool": "export_document",
                "document_path": str(_resolve_path(document_path)) if document_path else None,
                "output_tool": tool,
                "output_path": written["path"],
                "bytes_written": written["bytes_written"],
            },
        )
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


def import_file(
    tool: str,
    content: str | None = None,
    encoding: str = "utf-8",
    file_path: str | None = None,
) -> dict[str, Any]:
    """Import a format tool's native file into a ForgeLab document (as a dict).

    Provide the file either inline as ``content`` (with ``encoding`` ``utf-8`` or
    ``base64``) or, preferably, as ``file_path`` to a file on disk (a bare
    filename resolves against ``FORGELAB_OUTPUT_DIR``). A path also lets importers
    that need sibling files resolve them — e.g. ``tool='obj'`` reads the
    companion ``.mtl`` from the same directory. Exactly one of the two is allowed.
    """
    require_scope("forge:export")
    if content is not None and file_path is not None:
        raise ValueError("pass either content or file_path, not both")
    try:
        importer_cls = _registry.get_importer(tool)
    except UnknownToolError as exc:
        raise ValueError(str(exc)) from exc
    importer = importer_cls()
    if file_path is not None:
        path = _resolve_path(file_path)
        try:
            source = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"could not read file {str(path)!r}: {exc}") from exc
        if hasattr(importer, "base_dir"):
            importer.base_dir = path.parent
        if hasattr(importer, "source_name"):
            importer.source_name = path.stem
    elif content is not None:
        source = decode_content(content, encoding)
    else:
        raise ValueError("provide content (inline) or a file_path to the native file")
    document = importer.to_ir(source)
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


_VISION_MODEL = "claude-sonnet-4-6"

_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_VISION_ADDENDUM = (
    "You are analyzing an image to produce a STARTING ForgeLab {domain} document.\n"
    "- Identify the components, geometry, and structure visible in the image and "
    "model each as a node matching the {domain} schema above.\n"
    "- For any dimension or value you cannot read directly from the image, use a "
    "reasonable engineering estimate.\n"
    '- Whenever a value is an estimate, append "-estimated" to that node\'s id so a '
    'human can spot it (e.g. "U1-estimated").\n'
    "- This is a skeleton to be refined later; favour completeness of structure "
    "over precision.\n"
    "- Respond with ONLY the ForgeLab JSON document — no prose, no code fences."
)


def _image_media_type(path: Path) -> str:
    media = _IMAGE_MEDIA_TYPES.get(path.suffix.lower())
    if media is None:
        raise ValueError(
            f"unsupported image type {path.suffix!r}; supported: "
            f"{', '.join(sorted(_IMAGE_MEDIA_TYPES))}"
        )
    return media


def _make_vision_client() -> Any:
    """Construct an Anthropic client for vision calls. Indirection so tests inject."""
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise ImportError(
            'image analysis requires the agent extra (pip install "forgelab[agent]")'
        ) from exc
    return anthropic.Anthropic()


def _message_text(message: Any) -> str:
    """Concatenate the text blocks of an Anthropic message (object or dict blocks)."""
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", "") or "")
    return "".join(parts)


def _parse_skeleton_json(text: str) -> dict[str, Any]:
    """Parse a ForgeLab JSON document out of the model's text response."""
    candidate = text.strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            data = json.loads(_extract_json(candidate))
        except (LLMOutputError, json.JSONDecodeError) as exc:
            raise ValueError(f"image analysis did not return valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("image analysis did not return a JSON object")
    return data


def analyze_image(image_path: str, domain: str, hints: str = "") -> dict[str, Any]:
    """Analyze an image and return a starting ForgeLab document skeleton.

    Reads an image from disk and asks the Anthropic vision model
    (``claude-sonnet-4-6``) to describe what it sees as a partial ForgeLab
    document for ``domain``. Use it as the first step of a photo-to-design flow:
    snap a photo of a board/part/scene, get a skeleton, then refine it, validate
    it, and export it.

    Args:
        image_path: path to the image (``.png``, ``.jpg/.jpeg``, ``.gif`` or
            ``.webp``); a bare filename resolves against ``FORGELAB_OUTPUT_DIR``.
        domain: one of ``hardware``, ``mechanical`` or ``threed``.
        hints: optional free text to steer the analysis (e.g. "approximate
            dimensions are 100x60mm", "this is a 4-layer board").

    Returns:
        The model's ForgeLab document as a dict. It is a *skeleton*: visible
        structure is extracted and unreadable values are reasonable estimates,
        with estimated nodes' ids suffixed ``-estimated``. Validate it with
        ``validate_document`` after refining. Requires ``ANTHROPIC_API_KEY`` and
        the ``agent`` extra (see ``generation_status``); scope ``forge:generate``.
    """
    require_scope("forge:generate")
    if domain not in DOMAIN_VOCAB:
        raise ValueError(f"unknown domain: {domain!r}; valid domains: {sorted(DOMAIN_VOCAB)}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("image analysis unavailable: ANTHROPIC_API_KEY is not set on the server")
    path = _resolve_path(image_path)
    media_type = _image_media_type(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read image {str(path)!r}: {exc}") from exc
    try:
        client = _make_vision_client()
    except ImportError as exc:
        raise ValueError(
            'image analysis unavailable: install the agent extra (pip install "forgelab[agent]")'
        ) from exc

    user_text = "Analyze this image and produce the ForgeLab document."
    if hints.strip():
        user_text += f"\n\nHints from the user: {hints.strip()}"
    message = client.messages.create(
        model=_VISION_MODEL,
        max_tokens=8192,
        system=system_prompt(domain) + "\n\n" + _VISION_ADDENDUM.format(domain=domain),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(raw).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )
    return _parse_skeleton_json(_message_text(message))


# --------------------------------------------------------------------------- #
# Render-critique loop primitives. Two deliberately separate tools — the
# calling agent drives the iteration itself: preview_render -> critique_render
# -> patch_document from the suggested changes -> render again.
# --------------------------------------------------------------------------- #
def _import_preview() -> Any:
    """Import the preview renderer. Indirection so tests can simulate absence."""
    from forgelab import preview

    return preview


def _preview_extra_installed() -> bool:
    return (
        importlib.util.find_spec("matplotlib") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def preview_render(document_path: str, output_path: str, views: int = 3) -> dict[str, Any]:
    """Render a threed document to a flat-shaded multi-angle preview PNG.

    Pure-local computation (matplotlib, no Blender, no GPU): each object's
    transform is applied to its mesh triangles and up to four camera angles
    (front-3/4, side, rear-3/4, top) are laid side by side in one PNG, so an
    agent can *see* the shape it built without the user screenshotting
    anything. Renders the baked triangle geometry; Blender modifier stacks are
    evaluated by Blender itself, so previews show the base meshes. Pair with
    ``critique_render`` for the iterative refine loop.

    Args:
        document_path: path to the threed ``.forge.json`` (a bare filename
            resolves against ``FORGELAB_OUTPUT_DIR``).
        output_path: where to write the preview PNG.
        views: how many camera angles to render, 1-4 (default 3).

    Returns:
        ``{"rendered": true, "path", "triangle_count", "views"}``. Requires
        the ``preview`` extra (see ``generation_status``); scope ``forge:read``.
    """
    require_scope("forge:read")
    data = _read_document_file(document_path)
    try:
        document_model = _core_validate(data)
    except Exception as exc:
        raise ValueError(f"invalid document: {exc}") from exc
    try:
        preview = _import_preview()
    except ImportError as exc:
        raise ValueError(
            "preview rendering unavailable: install the preview extra "
            '(pip install "forgelab[preview]")'
        ) from exc
    target = _resolve_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = preview.render_preview(document_model, str(target), views=views)
    except ImportError as exc:
        raise ValueError(
            "preview rendering unavailable: install the preview extra "
            '(pip install "forgelab[preview]")'
        ) from exc
    return {
        "rendered": True,
        "path": str(target),
        "triangle_count": result["triangle_count"],
        "views": result["views"],
    }


_CRITIQUE_SYSTEM = """\
You are a meticulous 3D art director reviewing a render of a model against \
the designer's stated intent{reference_clause}. Judge shape, proportions, \
composition and completeness — not render quality (the preview is a simple \
flat-shaded diagnostic, so ignore lighting/materials/resolution).

Respond with ONLY a single JSON object, no prose and no Markdown fences:
{{
  "matches_intent": <bool — does the model plausibly realize the intent?>,
  "score": <0-10 integer; 8+ means ship it>,
  "issues": [
    {{
      "severity": "critical" | "minor",
      "description": "<what is wrong, visually specific>",
      "likely_cause": "<the probable modelling cause, e.g. a missing object \
or a wrong transform/scale>"
    }}
  ],
  "suggested_changes": [
    "<specific, actionable edit, e.g. 'increase greenhouse height by ~30%', \
'add a fourth wheel at the rear-left', 'wheel arches are too small — \
increase radius'>"
  ]
}}"""


def critique_render(
    render_path: str, intent: str, reference_image_path: str | None = None
) -> dict[str, Any]:
    """Critique a rendered preview against the design intent via the vision API.

    Sends the preview PNG (from ``preview_render``) — plus an optional
    reference image — to the vision model with the intent description, and
    returns its structured verdict: ``{"matches_intent": bool, "score": 0-10,
    "issues": [{"severity", "description", "likely_cause"}],
    "suggested_changes": [...]}``. Drive the refine loop yourself: apply the
    suggested changes with ``patch_document``, re-render, and re-critique
    until the score is acceptable or your turn budget runs out.

    Args:
        render_path: path to the rendered preview image; a bare filename
            resolves against ``FORGELAB_OUTPUT_DIR``.
        intent: what the model is supposed to be, in plain language (e.g.
            "a low-slung sports car with a long hood and a fastback roof").
        reference_image_path: optional photo/concept image the model should
            match; sent alongside the render when provided.

    Returns:
        The parsed critique dict. Requires ``ANTHROPIC_API_KEY`` and the
        ``agent`` extra (see ``generation_status``); scope ``forge:generate``.
    """
    require_scope("forge:generate")
    if not intent.strip():
        raise ValueError("critique_render needs an 'intent' description to judge against")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("render critique unavailable: ANTHROPIC_API_KEY is not set on the server")

    def image_block(path_str: str) -> dict[str, Any]:
        path = _resolve_path(path_str)
        media_type = _image_media_type(path)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"could not read image {str(path)!r}: {exc}") from exc
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(raw).decode("ascii"),
            },
        }

    content: list[dict[str, Any]] = [image_block(render_path)]
    reference_clause = ""
    if reference_image_path:
        content.append(image_block(reference_image_path))
        reference_clause = " and a reference image (the second image; the first is the render)"
    content.append({"type": "text", "text": f"Design intent: {intent.strip()}"})

    try:
        client = _make_vision_client()
    except ImportError as exc:
        raise ValueError(
            'render critique unavailable: install the agent extra (pip install "forgelab[agent]")'
        ) from exc
    message = client.messages.create(
        model=_VISION_MODEL,
        max_tokens=2048,
        system=_CRITIQUE_SYSTEM.format(reference_clause=reference_clause),
        messages=[{"role": "user", "content": content}],
    )
    text = _message_text(message)
    try:
        critique = json.loads(text)
    except json.JSONDecodeError:
        try:
            critique = json.loads(_extract_json(text))  # tolerate fenced/prose-wrapped JSON
        except (LLMOutputError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"vision model did not return parseable critique JSON: {text[:200]!r}"
            ) from exc
    if not isinstance(critique, dict):
        raise ValueError("vision model returned JSON that is not a critique object")
    critique.setdefault("issues", [])
    critique.setdefault("suggested_changes", [])
    return critique
