"""Base class for exporters: ForgeLab IR -> native tool format."""

from abc import ABC, abstractmethod

from forgelab.spec import ForgeDocument


class Exporter(ABC):
    """Convert a ForgeDocument into a tool's native file bytes.

    Subclasses set ``tool_name`` and implement ``from_ir``.
    """

    tool_name: str = ""

    @abstractmethod
    def from_ir(self, document: ForgeDocument) -> bytes:
        """Serialize ``document`` into the target tool's native bytes."""
        raise NotImplementedError
