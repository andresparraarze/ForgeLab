"""Base class for exporters: ForgeLab IR -> native tool format."""

from abc import ABC, abstractmethod
from pathlib import Path

from forgelab.spec import ForgeDocument


class Exporter(ABC):
    """Convert a ForgeDocument into a tool's native file bytes.

    Subclasses set ``tool_name`` and implement ``from_ir``. Stubs that only
    raise ``NotImplementedError`` set ``implemented = False`` so the registry
    (and ``list_formats``) reports them honestly as unavailable.

    Exporters that need to resolve a companion asset the document only names by
    relative path (a threed material's ``base_color_texture``) may read
    ``base_dir``, the document's own directory; the MCP ``export_document`` tool
    sets it when the document is given by path. It mirrors ``Importer.base_dir``
    and defaults to ``None``.
    """

    tool_name: str = ""
    implemented: bool = True
    base_dir: Path | None = None

    @abstractmethod
    def from_ir(self, document: ForgeDocument) -> bytes:
        """Serialize ``document`` into the target tool's native bytes."""
        raise NotImplementedError
