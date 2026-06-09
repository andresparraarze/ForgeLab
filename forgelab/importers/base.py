"""Base class for importers: native tool format -> ForgeLab IR."""

from abc import ABC, abstractmethod

from forgelab.spec import ForgeDocument


class Importer(ABC):
    """Convert a tool's native file bytes into a ForgeDocument.

    Subclasses set ``tool_name`` and implement ``to_ir``.
    """

    tool_name: str = ""

    @abstractmethod
    def to_ir(self, source: bytes) -> ForgeDocument:
        """Parse ``source`` bytes into a validated ForgeDocument."""
        raise NotImplementedError
