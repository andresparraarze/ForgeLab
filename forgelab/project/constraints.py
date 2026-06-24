"""Informational cross-domain constraint checking.

Each constraint compares a shared dimension (plus an optional offset) against a
value read from a target document via a JSON Pointer. Today the result is purely
advisory — violations are reported, never enforced — so a project can surface
drift between, say, a board outline and the enclosure built around it without
blocking either side's export.
"""

from __future__ import annotations

from typing import Any

from forgelab.patch.jsonpointer import resolve
from forgelab.project.model import Constraint, Project

_SHARED_PREFIX = "shared."


def _shared_value(project: Project, source: str) -> float | None:
    """Resolve a ``shared.<key>`` reference to its value, or None if absent."""
    if not source.startswith(_SHARED_PREFIX):
        return None
    return project.shared.get(source[len(_SHARED_PREFIX) :])


def _evaluate(constraint: Constraint, expected: float, actual: float) -> tuple[bool, str]:
    """Apply a constraint ``type`` to (expected, actual); return (satisfied, op)."""
    kind = constraint.type
    if kind == "max_value":
        return actual <= expected, "<="
    if kind == "exact_value":
        return abs(actual - expected) < 1e-9, "=="
    # Default and explicit "min_value": the target must be at least the expected.
    return actual >= expected, ">="


def check_constraint(
    constraint: Constraint, project: Project, documents: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Evaluate one constraint, returning a structured report (never raises)."""
    report: dict[str, Any] = {
        "description": constraint.description,
        "type": constraint.type,
        "source": constraint.source,
        "target_document": constraint.target_document,
        "target_path": constraint.target_path,
        "satisfied": True,
    }
    source_value = _shared_value(project, constraint.source)
    if source_value is None:
        report["satisfied"] = False
        report["message"] = f"source {constraint.source!r} is not a known shared dimension"
        return report
    document = documents.get(constraint.target_document)
    if document is None:
        report["satisfied"] = False
        report["message"] = f"target document {constraint.target_document!r} is not in the project"
        return report
    try:
        actual = resolve(document, constraint.target_path)
    except Exception as exc:  # an unresolvable pointer is a reported violation
        report["satisfied"] = False
        report["message"] = f"target_path {constraint.target_path!r} did not resolve: {exc}"
        return report
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        report["satisfied"] = False
        report["message"] = f"target value {actual!r} is not numeric"
        return report

    expected = source_value + constraint.offset
    actual_f = float(actual)
    satisfied, op = _evaluate(constraint, expected, actual_f)
    report["expected"] = expected
    report["actual"] = actual_f
    report["satisfied"] = satisfied
    if not satisfied:
        report["message"] = (
            f"expected {constraint.target_path} ({actual_f}) {op} "
            f"{constraint.source} + {constraint.offset} ({expected})"
        )
    return report


def check_constraints(
    project: Project, documents: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Evaluate every project constraint against the loaded documents."""
    return [check_constraint(c, project, documents) for c in project.constraints]
