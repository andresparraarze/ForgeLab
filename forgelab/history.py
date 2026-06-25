"""Design history tracking for ForgeLab documents and projects.

Write tools (``patch_document``, ``export_document``, ``export_project``,
``update_project``) append a timestamped entry to a ``.forge.history`` file in the
same directory as the document or project they touched. The file is a JSON array
of entries, newest last, capped at :data:`MAX_ENTRIES` (oldest trimmed first).

History is best-effort: ``record`` never raises, so a tool's primary work is
never blocked by a history write that fails. The file is optional — it is created
on first write and absent until then.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HISTORY_FILENAME = ".forge.history"
MAX_ENTRIES = 100


def history_path_for(path: Path) -> Path:
    """The ``.forge.history`` file that sits beside ``path``."""
    return path.parent / HISTORY_FILENAME


def _now() -> str:
    return datetime.now(UTC).isoformat()


def read_history(path: Path) -> list[dict[str, Any]]:
    """Return the entries from the history file beside ``path`` (``[]`` if none).

    Never raises: a missing, unreadable, or malformed history file yields ``[]``.
    """
    history_file = history_path_for(path)
    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def record(path: Path, entry: dict[str, Any]) -> None:
    """Append ``entry`` (timestamped) to the history file beside ``path``.

    Best-effort: any failure is swallowed so the caller's write is never blocked.
    A ``timestamp`` is added if the entry does not already carry one, and the file
    is trimmed to the newest :data:`MAX_ENTRIES`.
    """
    try:
        stamped = {"timestamp": entry.get("timestamp") or _now(), **entry}
        entries = read_history(path)
        entries.append(stamped)
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]
        history_file = history_path_for(path)
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history_file.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    except Exception:
        # History is auxiliary; never let it break the tool that called us.
        pass
