"""Neutral file-format primitives shared by importers and exporters.

Two members are imported by module rather than re-exported flat, because their
entry points have deliberately generic names (``available``, ``tessellate``,
``convert``, ``normalize``) that would be meaningless in this namespace::

    from forgelab.formats import freecad_kernel, step

Only their error type is re-exported here, matching ``FcstdError``/``GltfError``.
"""

from forgelab.formats.fcstd import (
    FcDocument,
    FcObject,
    FcProperty,
    FcstdError,
    read_archive_entry,
    read_document,
    read_objects,
    write_archive,
    write_fcstd,
)
from forgelab.formats.freecad_kernel import FreeCADKernelError
from forgelab.formats.gltf import (
    ARRAY_BUFFER,
    ELEMENT_ARRAY_BUFFER,
    FLOAT,
    UNSIGNED_INT,
    UNSIGNED_SHORT,
    BufferBuilder,
    GltfError,
    decode_accessor,
)
from forgelab.formats.sexpr import SExpr, SExprError, Symbol, dumps, parse

__all__ = [
    "SExpr",
    "SExprError",
    "Symbol",
    "dumps",
    "parse",
    "ARRAY_BUFFER",
    "ELEMENT_ARRAY_BUFFER",
    "FLOAT",
    "UNSIGNED_INT",
    "UNSIGNED_SHORT",
    "BufferBuilder",
    "GltfError",
    "decode_accessor",
    "FcDocument",
    "FcObject",
    "FcProperty",
    "FcstdError",
    "FreeCADKernelError",
    "read_archive_entry",
    "read_document",
    "read_objects",
    "write_archive",
    "write_fcstd",
]
