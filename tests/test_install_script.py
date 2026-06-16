"""Tests for the PATH-setup logic in scripts/install-claude-code.sh.

The installer is curl|bash, so its PATH logic must live in that one file; to
test it we source the script with FORGELAB_INSTALLER_TEST=1 (which stops it
after the helper definitions) and call the helper directly. The key regression:
zsh on Arch/EndeavourOS relocates its dotfiles via $ZDOTDIR (commonly
~/.config/zsh), so writing to a bare ~/.zshrc leaves the PATH export in a file
zsh never reads.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/install-claude-code.sh").resolve()

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _run_setup(tmp_path: Path, *, zsh_zdotdir: str | None, make_bashrc: bool = False) -> Path:
    """Run forgelab_setup_path in an isolated HOME; return that HOME.

    If ``zsh_zdotdir`` is given, a stub ``zsh`` is placed on PATH that reports
    it (emulating zsh resolving $ZDOTDIR from .zshenv). Otherwise no zsh is on
    PATH, exercising the ~/$HOME fallback.
    """
    home = tmp_path / "home"
    home.mkdir()
    binbase = "/usr/bin:/bin"

    stub_dir = tmp_path / "stubbin"
    stub_dir.mkdir()
    if zsh_zdotdir is not None:
        zsh = stub_dir / "zsh"
        # Ignores args; just prints the resolved dotfile dir like
        # `zsh -c 'print -rn -- ${ZDOTDIR:-$HOME}'` would.
        zsh.write_text(f'#!/bin/sh\nprintf %s "{zsh_zdotdir}"\n')
        zsh.chmod(0o755)

    if make_bashrc:
        (home / ".bashrc").write_text("# existing bashrc\n")

    path_env = f"{stub_dir}:{binbase}"
    cmd = f"set -euo pipefail; source '{SCRIPT}'; forgelab_setup_path '{home}/.forgelab/venv/bin'"
    result = subprocess.run(
        ["bash", "-c", cmd],
        env={
            "HOME": str(home),
            "PATH": path_env,
            "FORGELAB_INSTALLER_TEST": "1",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"setup failed:\n{result.stdout}\n{result.stderr}"
    return home


def _expected_line(home: Path) -> str:
    return f'export PATH="{home}/.forgelab/venv/bin:$PATH"'


def test_path_written_to_zdotdir_when_zsh_relocates_dotfiles(tmp_path):
    # Arch/EndeavourOS: ZDOTDIR=~/.config/zsh. The export must land in the files
    # zsh actually reads, not a stray ~/.zshrc it ignores.
    home = _run_setup(tmp_path, zsh_zdotdir=str(tmp_path / "home" / ".config" / "zsh"))
    zdir = home / ".config" / "zsh"
    line = _expected_line(home)
    assert line in (zdir / ".zshrc").read_text()
    assert line in (zdir / ".zprofile").read_text()
    # The bare ~/.zshrc (which zsh ignores here) must NOT be where it stops.
    assert not (home / ".zshrc").exists() or line not in (home / ".zshrc").read_text()


def test_path_written_to_home_when_no_zdotdir(tmp_path):
    # Plain zsh with ZDOTDIR unset → $HOME. Stub prints $HOME.
    home_dir = str(tmp_path / "home")
    home = _run_setup(tmp_path, zsh_zdotdir=home_dir)
    line = _expected_line(home)
    assert line in (home / ".zshrc").read_text()
    assert line in (home / ".zprofile").read_text()


def test_path_written_to_home_when_zsh_absent(tmp_path):
    # No zsh on PATH → fall back to ~/.zshrc and ~/.zprofile.
    home = _run_setup(tmp_path, zsh_zdotdir=None)
    line = _expected_line(home)
    assert line in (home / ".zshrc").read_text()
    assert line in (home / ".zprofile").read_text()


def test_zprofile_is_always_written(tmp_path):
    # The reported fix: login shells (Arch terminal emulators, SSH) read
    # .zprofile, not .zshrc — it must always get the export.
    home = _run_setup(tmp_path, zsh_zdotdir=str(tmp_path / "home"))
    assert (home / ".zprofile").exists()
    assert _expected_line(home) in (home / ".zprofile").read_text()


def test_append_is_idempotent(tmp_path):
    home = _run_setup(tmp_path, zsh_zdotdir=str(tmp_path / "home"))
    # Re-run setup against the same HOME (no zsh on PATH → $HOME fallback, same
    # files). The export line must not be duplicated.
    cmd = f"set -euo pipefail; source '{SCRIPT}'; forgelab_setup_path '{home}/.forgelab/venv/bin'"
    subprocess.run(
        ["bash", "-c", cmd],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "FORGELAB_INSTALLER_TEST": "1"},
        check=True,
        capture_output=True,
        text=True,
    )
    line = _expected_line(home)
    assert (home / ".zshrc").read_text().count(line) == 1
    assert (home / ".zprofile").read_text().count(line) == 1


def test_bashrc_updated_only_when_present(tmp_path):
    home = _run_setup(tmp_path, zsh_zdotdir=str(tmp_path / "home"), make_bashrc=True)
    assert _expected_line(home) in (home / ".bashrc").read_text()
