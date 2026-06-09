"""Validate untrusted input against the ForgeLab IR."""

from typing import Any

from forgelab.core.errors import IncompatibleVersionError
from forgelab.spec import ForgeDocument
from forgelab.spec.version import is_compatible


def validate(data: dict[str, Any]) -> ForgeDocument:
    """Parse and validate ``data`` into a ForgeDocument.

    Raises:
        IncompatibleVersionError: if the document's spec major version differs.
        pydantic.ValidationError: if the document is structurally invalid.
    """
    version = data.get("forgelab_version")
    if not isinstance(version, str) or not is_compatible(version):
        raise IncompatibleVersionError(
            f"Document forgelab_version {version!r} is not compatible with this library."
        )
    return ForgeDocument.model_validate(data)
