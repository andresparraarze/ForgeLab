"""ForgeLab error hierarchy."""


class ForgeError(Exception):
    """Base class for all ForgeLab errors."""


class IncompatibleVersionError(ForgeError):
    """Raised when a document's spec version is incompatible with this library."""


class UnknownToolError(ForgeError):
    """Raised when no importer/exporter is registered for a tool name."""


class LLMOutputError(ForgeError):
    """Raised when raw LLM output cannot be cleaned/parsed/validated into IR."""
