"""Move the CHANGELOG's Unreleased section under a version heading.

Keep a Changelog's shape, which this file already follows: an [Unreleased]
section at the top collects work as it lands, and cutting a release renames it
to the version, dates it, and opens a fresh empty [Unreleased] above it. The
comparison links at the bottom are rewritten to match.

Called by scripts/release.sh; kept separate because doing this in shell means
either a fragile sed or a heredoc nobody can read.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
REPO = "https://github.com/andresparraarze/ForgeLab"

UNRELEASED = "## [Unreleased]"
PLACEHOLDER = "Nothing yet."
NEW_UNRELEASED = f"{UNRELEASED}\n\n{PLACEHOLDER}\n"


def cut(text: str, version: str, today: str) -> str:
    if UNRELEASED not in text:
        raise SystemExit("CHANGELOG has no [Unreleased] section.")

    head, _, body = text.partition(UNRELEASED)
    # Only the Unreleased *section* is being cut: everything up to the next
    # release heading. Partitioning on the whole remainder would treat the
    # previous release's body as unreleased work, so an empty section would
    # look full and cut a release with no entries in it.
    match = re.search(r"^## \[", body, flags=re.M)
    section, rest = (body[: match.start()], body[match.start() :]) if match else (body, "")

    released = section.strip("\n")
    if released.strip() in ("", PLACEHOLDER.strip()):
        raise SystemExit("[Unreleased] is empty — nothing to release.")

    text = f"{head}{NEW_UNRELEASED}\n## [{version}] - {today}\n\n{released}\n\n{rest}"

    # Link definitions live at the bottom; rewrite Unreleased to compare against
    # the new tag and add a definition for the tag itself.
    previous = _previous_version(text, version)
    unreleased_link = f"[Unreleased]: {REPO}/compare/v{version}...HEAD"
    version_link = (
        f"[{version}]: {REPO}/compare/v{previous}...v{version}"
        if previous
        else f"[{version}]: {REPO}/releases/tag/v{version}"
    )

    if re.search(r"^\[Unreleased\]: .*$", text, flags=re.M):
        text = re.sub(r"^\[Unreleased\]: .*$", unreleased_link, text, count=1, flags=re.M)
        text = text.replace(unreleased_link, f"{unreleased_link}\n{version_link}", 1)
    else:
        text = text.rstrip("\n") + f"\n\n{unreleased_link}\n{version_link}\n"
    return text


def _previous_version(text: str, version: str) -> str | None:
    """The most recent released version other than the one being cut."""
    found = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.M)
    return next((v for v in found if v != version), None)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: cut_changelog.py X.Y.Z")
    version = sys.argv[1]
    today = dt.date.today().isoformat()
    CHANGELOG.write_text(cut(CHANGELOG.read_text(), version, today))
    print(f"CHANGELOG: [Unreleased] -> [{version}] - {today}")


if __name__ == "__main__":
    main()
