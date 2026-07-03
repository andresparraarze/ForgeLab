"""Base class for exporters: ForgeLab IR -> native tool format."""

from abc import ABC, abstractmethod

from forgelab.spec import ForgeDocument


class Exporter(ABC):
    """Convert a ForgeDocument into a tool's native file bytes.

    Subclasses set ``tool_name`` and implement ``from_ir``. Stubs that only
    raise ``NotImplementedError`` set ``implemented = False`` so the registry
    (and ``list_formats``) reports them honestly as unavailable.
    """

    tool_name: str = ""
    implemented: bool = True

    @abstractmethod
    def from_ir(self, document: ForgeDocument) -> bytes:
        """Serialize ``document`` into the target tool's native bytes."""
        raise NotImplementedError
