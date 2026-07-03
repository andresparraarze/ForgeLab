"""Base class for importers: native tool format -> ForgeLab IR."""

from abc import ABC, abstractmethod
from pathlib import Path

from forgelab.spec import ForgeDocument


class Importer(ABC):
    """Convert a tool's native file bytes into a ForgeDocument.

    Subclasses set ``tool_name`` and implement ``to_ir``. Importers that need the
    source file's location (e.g. to read a sibling file like an OBJ's ``.mtl``)
    or its name may read ``base_dir``/``source_name``; the MCP ``import_file``
    tool sets them when a file is imported by path. Both default to ``None``.
    """

    tool_name: str = ""
    implemented: bool = True
    base_dir: Path | None = None
    source_name: str | None = None

    @abstractmethod
    def to_ir(self, source: bytes) -> ForgeDocument:
        """Parse ``source`` bytes into a validated ForgeDocument."""
        raise NotImplementedError
