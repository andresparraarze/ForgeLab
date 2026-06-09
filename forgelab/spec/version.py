"""ForgeLab spec versioning.

Every ForgeDocument declares a ``forgelab_version`` so tools can reason about
long-term compatibility. Compatibility is determined by the major version:
documents with a different major version than the running library are rejected.
"""

SPEC_VERSION = "0.1.0"


def is_compatible(version: str) -> bool:
    """Return True if ``version`` shares this library's spec major version."""
    try:
        doc_major = int(version.split(".")[0])
        spec_major = int(SPEC_VERSION.split(".")[0])
    except (ValueError, IndexError):
        return False
    return doc_major == spec_major
