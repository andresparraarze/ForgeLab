"""STEP (ISO 10303-21) header normalization for reproducible exports.

STEP files carry a wall-clock timestamp in their ``FILE_NAME`` header entry::

    FILE_NAME('Open CASCADE Shape Model','2026-09-06T08:59:10',('FreeCAD'),(
        'FreeCAD'),'Open CASCADE STEP processor 7.9','FreeCAD','Unknown');

so exporting the same document twice a second apart produces different bytes.
That breaks the round-trip determinism the rest of ForgeLab guarantees, and it
embeds environment state — the same thing
``test_generated_scripts_embed_no_environment_state`` forbids in generated
Blender scripts. :func:`normalize` rewrites the stamp to a fixed epoch, the
same trick the FCStd writer uses for its ZIP entries.

Scope of the guarantee, stated honestly: this makes an export byte-identical
across *runs*, not across *toolchains*. The header also names the producing
kernel (``Open CASCADE STEP processor 7.9``) and the geometry itself comes from
that kernel, so a different FreeCAD/OCC build may legitimately write different
bytes. Pinning the version out of the header would hide that rather than fix it.

Neutral primitive: standard library only, no forgelab imports.
"""

from __future__ import annotations

import re

#: The fixed stamp written in place of the real time. Matches the FCStd
#: writer's ``_ZIP_DATE`` epoch so both formats tell the same story.
FIXED_TIMESTAMP = "1980-01-01T00:00:00"

_HEADER_END = b"ENDSEC;"
_TIMESTAMP_RE = re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def normalize(data: bytes) -> bytes:
    """Replace the STEP header's wall-clock timestamp with a fixed epoch.

    Only the HEADER section is touched — the search stops at the first
    ``ENDSEC;`` — so no coordinate or string in the DATA section can be
    rewritten by accident. Input that carries no timestamp (or no header at
    all) is returned unchanged.
    """
    end = data.find(_HEADER_END)
    if end == -1:
        return data
    header, rest = data[:end], data[end:]
    return _TIMESTAMP_RE.sub(FIXED_TIMESTAMP.encode("ascii"), header) + rest
