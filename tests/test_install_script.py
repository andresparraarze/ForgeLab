"""Tests for the PATH-setup logic in scripts/install.sh.

The installer is curl|bash, so its PATH logic must live in that one file
(install.sh is the generic core; install-claude-code.sh and install-codex.sh
are thin registration wrappers around it); to test it we source the script
with FORGELAB_INSTALLER_TEST=1 (which stops it after the helper definitions)
and call the helper directly. The key regression:
zsh on Arch/EndeavourOS relocates its dotfiles via $ZDOTDIR (commonly
~/.config/zsh), so writing to a bare ~/.zshrc leaves the PATH export in a file
zsh never reads.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/install.sh").resolve()

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


# --- the four agent wrappers ------------------------------------------------
#
# The wrappers are deliberately thin: registration lives in `forgelab init`
# (see tests/test_cli_init.py), which is the only place the per-CLI flags are
# written down. What these tests protect is that the wrappers keep delegating
# rather than growing a second, drifting copy of `<agent> mcp add`.

WRAPPERS = {
    "install-claude-code.sh": ("claude-code", "claude"),
    "install-codex.sh": ("codex", "codex"),
    "install-hermes.sh": ("hermes", "hermes"),
    "install-openclaw.sh": ("openclaw", "openclaw"),
}


def _code(script: str) -> list[str]:
    """The wrapper's executable lines — comments explain the flags, so a
    substring search over the whole file would match the explanation."""
    lines = (Path("scripts") / script).read_text().splitlines()
    return [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


@pytest.mark.parametrize("script,expected", sorted(WRAPPERS.items()))
def test_wrapper_delegates_registration_to_forgelab_init(script, expected):
    agent, binary = expected
    code = _code(script)

    assert any(f"init --agent {agent}" in ln for ln in code)
    assert any(f"command -v {binary}" in ln for ln in code)
    # No hand-rolled registration: that is what `forgelab init` is for.
    assert not any(f"{binary} mcp add" in ln for ln in code)


@pytest.mark.parametrize("script", sorted(WRAPPERS))
def test_wrapper_does_not_let_a_prompt_eat_the_install_script(script):
    """Under `curl ... | bash` the script itself is stdin.

    Hermes and OpenClaw probe the server and then ask before saving; without a
    redirect they would consume the remaining lines of the installer.
    """
    init_line = next(ln for ln in _code(script) if "init --agent" in ln)
    assert "</dev/null" in init_line


@pytest.mark.parametrize("script", sorted(WRAPPERS) + ["install.sh"])
def test_scripts_are_executable_and_valid_bash(script):
    path = Path("scripts") / script
    assert path.stat().st_mode & 0o111, f"{script} is not executable"
    subprocess.run(["bash", "-n", str(path)], check=True)


def test_installer_installs_the_extras_the_mcp_tools_need():
    """preview_render and critique_render are 2 of the 40 tools.

    Without matplotlib/numpy they are the two that fail on a machine where
    everything else works — and nothing else in the dependency tree pulls them.
    """
    body = SCRIPT.read_text()
    assert body.count("[mcp,agent,preview]") >= 2
    assert "[mcp,agent]" not in body.replace("[mcp,agent,preview]", "")


def test_installer_upgrades_rather_than_reusing_an_existing_install():
    """pip 23.x and older refuse to reinstall a git URL at an unchanged version.

    That made re-running the one-liner a silent no-op. The version is derived
    from git now, but --upgrade is what makes the intent explicit.
    """
    installs = [ln for ln in SCRIPT.read_text().splitlines() if 'pip" install' in ln]
    forgelab_installs = [ln for ln in installs if "forgelab" in ln]
    assert forgelab_installs
    assert all("--upgrade" in ln for ln in forgelab_installs), forgelab_installs
