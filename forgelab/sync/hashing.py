"""Canonical hashing of a ForgeLab document, for native-file sync checks.

Exporters embed ``document_hash`` of the document they compiled into the native
file (where the format allows). ``verify_sync`` later recomputes the hash from
the ``.forge.json`` on disk and compares, so an agent can tell whether a native
file is still in sync with its source document before patching.

Pure standard library.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Name under which exporters embed the hash (KiCad property / glTF extras key).
# FreeCAD uses an XML attribute named "Hash"; see the exporter and reader.
HASH_KEY = "forgelab_hash"


def document_hash(data: dict[str, Any]) -> str:
    """Return the SHA256 of a ForgeLab document's canonical JSON.

    ``data`` must be a JSON-serializable dict — typically
    ``ForgeDocument.model_dump(mode="json")``. Keys are sorted and insignificant
    whitespace removed so the hash depends only on the document's content, not on
    formatting or key order.
    """
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
