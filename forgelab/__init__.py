"""ForgeLab — the universal design interchange format and compiler."""

from importlib.metadata import PackageNotFoundError, version

from forgelab.spec.version import SPEC_VERSION

__all__ = ["SPEC_VERSION", "__version__"]

try:
    # Derived from git at build time (see [tool.hatch.version]), so this is the
    # one place the build's identity lives. A literal here would be a second
    # copy that silently drifts from the installed distribution's metadata.
    __version__ = version("forgelab")
except PackageNotFoundError:  # pragma: no cover - a source tree with no install
    __version__ = "0.0.0+unknown"
