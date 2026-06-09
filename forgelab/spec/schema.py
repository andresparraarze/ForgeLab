"""Export the ForgeLab IR as JSON Schema for non-Python consumers."""

from typing import Any

from forgelab.spec.models import ForgeDocument


def json_schema() -> dict[str, Any]:
    """Return the JSON Schema for a ForgeDocument."""
    return ForgeDocument.model_json_schema()
