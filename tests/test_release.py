"""Cutting a release: the CHANGELOG rewrite, and what release.sh refuses.

The version is not stored anywhere — hatch-vcs derives it from the git tag, so
`git tag v0.1.0` *is* the version bump. What still has to be got right is the
CHANGELOG, and the guards that stop a release being cut from a red, dirty, or
empty tree. Those are what these tests cover.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cut_changelog import cut  # noqa: E402

RELEASE = Path("scripts/release.sh").resolve()

HEADER = """# Changelog

Blurb.

"""


def _changelog(unreleased: str, tail: str = "") -> str:
    return f"{HEADER}## [Unreleased]\n\n{unreleased}\n{tail}"


def test_unreleased_work_moves_under_the_new_version():
    text = _changelog("### Added\n- a thing.")
    out = cut(text, "0.1.0", "2026-09-09")

    assert "## [0.1.0] - 2026-09-09" in out
    assert "- a thing." in out
    # The section that collects the next release is left open and empty.
    assert out.index("## [Unreleased]") < out.index("## [0.1.0]")
    assert out.count("## [Unreleased]") == 1


def test_an_empty_unreleased_section_is_refused():
    """Otherwise a release ships with no entries and nobody notices."""
    with pytest.raises(SystemExit):
        cut(_changelog("Nothing yet."), "0.1.1", "2026-09-10")


def test_a_previous_release_is_not_mistaken_for_unreleased_work():
    """The bug this test was written for.

    Splitting on [Unreleased] and taking everything after it swept the previous
    release's body along as though it were new — so an empty section looked
    full, and cutting twice in a row was allowed.
    """
    text = _changelog("Nothing yet.", tail="\n## [0.1.0] - 2026-09-09\n\n### Added\n- old work.\n")
    with pytest.raises(SystemExit):
        cut(text, "0.1.1", "2026-09-10")


def test_the_previous_release_body_is_left_alone():
    text = _changelog("### Fixed\n- new work.", tail="\n## [0.1.0] - 2026-09-09\n\n- old work.\n")
    out = cut(text, "0.1.1", "2026-09-10")

    assert out.index("## [0.1.1]") < out.index("## [0.1.0]")
    assert "- old work." in out
    assert "- new work." in out


def test_the_first_release_links_to_its_tag_and_later_ones_compare():
    first = cut(_changelog("### Added\n- a thing."), "0.1.0", "2026-09-09")
    assert "[0.1.0]: https://github.com/andresparraarze/ForgeLab/releases/tag/v0.1.0" in first
    assert (
        "[Unreleased]: https://github.com/andresparraarze/ForgeLab/compare/v0.1.0...HEAD" in first
    )

    second = cut(first.replace("Nothing yet.", "### Fixed\n- more."), "0.1.1", "2026-09-10")
    assert "[0.1.1]: https://github.com/andresparraarze/ForgeLab/compare/v0.1.0...v0.1.1" in second
    assert "[0.1.0]: https://github.com/andresparraarze/ForgeLab/releases/tag/v0.1.0" in second
    assert second.count("[Unreleased]: ") == 1


def test_links_point_at_this_repository():
    """They pointed at github.com/forgelab/forgelab, which is a different repo."""
    out = cut(_changelog("### Added\n- a thing."), "0.1.0", "2026-09-09")
    assert "forgelab/forgelab" not in out


# --- the shell guards -------------------------------------------------------


@pytest.mark.skipif(not RELEASE.exists(), reason="release.sh missing")
@pytest.mark.parametrize(
    "argument,expected",
    [("", "usage"), ("sideways", "unrecognized bump"), ("1.2", "unrecognized bump")],
)
def test_release_rejects_a_bad_bump_before_touching_anything(tmp_path, argument, expected):
    args = [str(RELEASE)] + ([argument] if argument else [])
    result = subprocess.run(args, capture_output=True, text=True, cwd=tmp_path)

    assert result.returncode != 0
    assert expected in (result.stdout + result.stderr).lower()


def test_release_derives_the_version_and_stores_it_nowhere():
    """A literal version in the tree would be a second copy to forget."""
    body = RELEASE.read_text()
    assert "hatch-vcs" in body
    pyproject = Path("pyproject.toml").read_text()
    assert 'dynamic = ["version"]' in pyproject
    # fallback-version is not a stored version: it is only reached when there is
    # no git metadata at all, e.g. building from a source tarball.
    assert "\nversion = " not in pyproject
