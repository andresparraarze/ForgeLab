"""ForgeLab error hierarchy."""


class ForgeError(Exception):
    """Base class for all ForgeLab errors."""


class IncompatibleVersionError(ForgeError):
    """Raised when a document's spec version is incompatible with this library."""


class UnknownToolError(ForgeError):
    """Raised when no importer/exporter is registered for a tool name."""
