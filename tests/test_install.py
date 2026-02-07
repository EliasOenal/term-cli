"""
Tests for install.sh — the term-cli installer.

These tests exercise install, reinstall, uninstall, flag parsing,
skill file management, and download mode.

Note: These tests do NOT require tmux (the installer only checks for it
and warns if missing). They use temporary directories for all file operations.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Callable

import pytest

INSTALL_SH = Path(__file__).parent.parent / "install.sh"
TERM_CLI = Path(__file__).parent.parent / "term-cli"
TERM_ASSIST = Path(__file__).parent.parent / "term-assist"
SKILL_MD = Path(__file__).parent.parent / "skills" / "term-cli" / "SKILL.md"


def run_installer(
    *args: str,
    env_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run install.sh with the given arguments."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run(
        ["/bin/sh", str(INSTALL_SH), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


# ── Flag parsing ───────────────────────────────────────────────────────


class TestFlagParsing:
    """Test argument parsing and validation."""

    def test_help(self) -> None:
        result = run_installer("--help")
        assert result.returncode == 0
        assert "Usage:" in result.stdout
        assert "--system" in result.stdout
        assert "--prefix" in result.stdout
        assert "--uninstall" in result.stdout

    def test_help_short(self) -> None:
        result = run_installer("-h")
        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_unknown_flag(self) -> None:
        result = run_installer("--bad-flag")
        assert result.returncode != 0
        assert "Unknown option" in result.stderr

    def test_prefix_requires_argument(self) -> None:
        result = run_installer("--prefix")
        assert result.returncode != 0
        assert "--prefix requires" in result.stderr

    def test_skill_requires_argument(self) -> None:
        result = run_installer("--skill")
        assert result.returncode != 0
        assert "--skill requires" in result.stderr

    def test_system_and_prefix_conflict(self) -> None:
        result = run_installer("--system", "--prefix", "/tmp/test")
        assert result.returncode != 0
        assert "cannot be used together" in result.stderr


# ── Install ────────────────────────────────────────────────────────────


class TestInstall:
    """Test binary and skill file installation."""

    def test_install_binaries(self, tmp_path: Path) -> None:
        """Binaries are installed with correct permissions."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0

        for name in ("term-cli", "term-assist"):
            installed = bin_dir / name
            assert installed.exists(), f"{name} not installed"
            assert installed.stat().st_mode & 0o111, f"{name} not executable"

    def test_install_prints_each_file(self, tmp_path: Path) -> None:
        """Installer is verbose about every file it installs."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "Installing" in result.stdout
        assert "term-cli" in result.stdout
        assert "term-assist" in result.stdout

    def test_install_content_matches_source(self, tmp_path: Path) -> None:
        """Installed binaries have the same content as source files."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0

        assert (bin_dir / "term-cli").read_text() == TERM_CLI.read_text()
        assert (bin_dir / "term-assist").read_text() == TERM_ASSIST.read_text()

    def test_install_creates_bin_dir(self, tmp_path: Path) -> None:
        """Installer creates the bin directory if it doesn't exist."""
        bin_dir = tmp_path / "nonexistent" / "bin"
        assert not bin_dir.exists()
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert bin_dir.exists()

    def test_install_all_skills(self, tmp_path: Path) -> None:
        """Default install creates skill files for all known agents."""
        bin_dir = tmp_path / "bin"
        home = tmp_path / "home"
        home.mkdir()
        result = run_installer(
            "--prefix", str(bin_dir),
            env_override={"HOME": str(home)},
        )
        assert result.returncode == 0

        expected_dirs = [
            ".config/opencode/skills/term-cli",
            ".claude/skills/term-cli",
            ".copilot/skills/term-cli",
            ".gemini/skills/term-cli",
            ".agents/skills/term-cli",
            ".openclaw/skills/term-cli",
        ]
        for rel_dir in expected_dirs:
            skill_file = home / rel_dir / "SKILL.md"
            assert skill_file.exists(), f"Skill not installed: {skill_file}"
            assert skill_file.read_text() == SKILL_MD.read_text()

    def test_install_filtered_skills(self, tmp_path: Path) -> None:
        """--skill flag installs only to specified agents."""
        bin_dir = tmp_path / "bin"
        home = tmp_path / "home"
        home.mkdir()
        result = run_installer(
            "--prefix", str(bin_dir),
            "--skill", "opencode,claude",
            env_override={"HOME": str(home)},
        )
        assert result.returncode == 0

        # These should exist
        assert (home / ".config/opencode/skills/term-cli/SKILL.md").exists()
        assert (home / ".claude/skills/term-cli/SKILL.md").exists()

        # These should NOT exist
        assert not (home / ".copilot/skills/term-cli/SKILL.md").exists()
        assert not (home / ".gemini/skills/term-cli/SKILL.md").exists()
        assert not (home / ".agents/skills/term-cli/SKILL.md").exists()
        assert not (home / ".openclaw/skills/term-cli/SKILL.md").exists()

    def test_install_no_skill(self, tmp_path: Path) -> None:
        """--no-skill flag skips all skill installation."""
        bin_dir = tmp_path / "bin"
        home = tmp_path / "home"
        home.mkdir()
        result = run_installer(
            "--prefix", str(bin_dir),
            "--no-skill",
            env_override={"HOME": str(home)},
        )
        assert result.returncode == 0

        # No skill directories should be created
        for agent_dir in (".config/opencode", ".claude", ".copilot", ".gemini", ".agents", ".openclaw"):
            assert not (home / agent_dir).exists(), f"Skill dir created despite --no-skill: {agent_dir}"

    def test_install_unknown_skill_warns(self, tmp_path: Path) -> None:
        """Unknown agent name in --skill produces a warning."""
        bin_dir = tmp_path / "bin"
        home = tmp_path / "home"
        home.mkdir()
        result = run_installer(
            "--prefix", str(bin_dir), "--skill", "nonexistent",
            env_override={"HOME": str(home)},
        )
        assert result.returncode == 0
        assert "Unknown agent" in result.stderr


# ── Reinstall (idempotent) ─────────────────────────────────────────────


class TestReinstall:
    """Test that re-running the installer works correctly."""

    def test_reinstall_says_replacing(self, tmp_path: Path) -> None:
        """Second install says 'Replacing' instead of 'Installing'."""
        bin_dir = tmp_path / "bin"
        run_installer("--prefix", str(bin_dir), "--no-skill")

        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "Replacing" in result.stdout

    def test_reinstall_updates_content(self, tmp_path: Path) -> None:
        """Re-installing overwrites existing files."""
        bin_dir = tmp_path / "bin"
        run_installer("--prefix", str(bin_dir), "--no-skill")

        # Corrupt the installed file
        (bin_dir / "term-cli").write_text("corrupted")

        # Re-install should fix it
        run_installer("--prefix", str(bin_dir), "--no-skill")
        assert (bin_dir / "term-cli").read_text() == TERM_CLI.read_text()

    def test_reinstall_skills_says_replacing(self, tmp_path: Path) -> None:
        """Re-installing skills says 'Replacing'."""
        bin_dir = tmp_path / "bin"
        home = tmp_path / "home"
        home.mkdir()
        env = {"HOME": str(home)}

        run_installer("--prefix", str(bin_dir), "--skill", "opencode", env_override=env)
        result = run_installer("--prefix", str(bin_dir), "--skill", "opencode", env_override=env)
        assert result.returncode == 0
        assert "Replacing" in result.stdout


# ── Uninstall ──────────────────────────────────────────────────────────


class TestUninstall:
    """Test the --uninstall flag."""

    def test_uninstall_removes_binaries(self, tmp_path: Path) -> None:
        """Uninstall removes installed binaries."""
        bin_dir = tmp_path / "bin"
        run_installer("--prefix", str(bin_dir), "--no-skill")
        assert (bin_dir / "term-cli").exists()

        result = run_installer("--uninstall", "--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert not (bin_dir / "term-cli").exists()
        assert not (bin_dir / "term-assist").exists()

    def test_uninstall_removes_skills(self, tmp_path: Path) -> None:
        """Uninstall removes skill files but not directories."""
        bin_dir = tmp_path / "bin"
        home = tmp_path / "home"
        home.mkdir()
        env = {"HOME": str(home)}

        run_installer("--prefix", str(bin_dir), env_override=env)
        skill_file = home / ".config/opencode/skills/term-cli/SKILL.md"
        assert skill_file.exists()

        run_installer("--uninstall", "--prefix", str(bin_dir), env_override=env)
        assert not skill_file.exists()
        # Directory should still exist (we don't delete directories)
        assert skill_file.parent.exists()

    def test_uninstall_filtered_skills(self, tmp_path: Path) -> None:
        """Uninstall with --skill only removes specified agents' skill files."""
        bin_dir = tmp_path / "bin"
        home = tmp_path / "home"
        home.mkdir()
        env = {"HOME": str(home)}

        # Install for all agents
        run_installer("--prefix", str(bin_dir), env_override=env)

        # Uninstall only opencode skill
        run_installer("--uninstall", "--prefix", str(bin_dir), "--skill", "opencode", env_override=env)

        # opencode skill should be gone
        assert not (home / ".config/opencode/skills/term-cli/SKILL.md").exists()
        # Others should still exist
        assert (home / ".claude/skills/term-cli/SKILL.md").exists()

    def test_uninstall_missing_files_skips(self, tmp_path: Path) -> None:
        """Uninstall gracefully handles already-missing files."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        # Don't install anything first
        result = run_installer("--uninstall", "--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "Not found, skipping" in result.stdout

    def test_uninstall_prints_each_removal(self, tmp_path: Path) -> None:
        """Uninstall is verbose about each file removed."""
        bin_dir = tmp_path / "bin"
        run_installer("--prefix", str(bin_dir), "--no-skill")

        result = run_installer("--uninstall", "--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "Removing" in result.stdout
        assert "term-cli" in result.stdout
        assert "term-assist" in result.stdout


# ── PATH detection ─────────────────────────────────────────────────────


class TestPathDetection:
    """Test PATH warning and shell config hints."""

    def test_warns_when_bin_dir_not_on_path(self, tmp_path: Path) -> None:
        """Warns when install directory is not on PATH."""
        bin_dir = tmp_path / "bin"
        result = run_installer(
            "--prefix", str(bin_dir), "--no-skill",
            env_override={"PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0
        assert "not in your PATH" in result.stdout

    def test_no_warning_when_bin_dir_on_path(self, tmp_path: Path) -> None:
        """No warning when install directory is already on PATH."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True)
        result = run_installer(
            "--prefix", str(bin_dir), "--no-skill",
            env_override={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        )
        assert result.returncode == 0
        assert "not in your PATH" not in result.stdout

    def test_local_bin_shows_shell_config_hint(self, tmp_path: Path) -> None:
        """~/.local/bin PATH hint shows bash and zsh instructions."""
        home = tmp_path / "home"
        home.mkdir()
        local_bin = home / ".local" / "bin"
        result = run_installer(
            "--prefix", str(local_bin), "--no-skill",
            env_override={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0
        assert ".bashrc" in result.stdout
        assert ".zshrc" in result.stdout


# ── Prerequisites ──────────────────────────────────────────────────────


class TestPrerequisites:
    """Test prerequisite checking."""

    def test_detects_python(self, tmp_path: Path) -> None:
        """Reports python3 version."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "python3 found" in result.stdout

    def test_detects_tmux(self, tmp_path: Path) -> None:
        """Reports tmux version (or warns if missing)."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        # Either tmux is found or a warning is shown
        assert "tmux found" in result.stdout or "tmux not found" in result.stderr


# ── Download mode ──────────────────────────────────────────────────────


@pytest.mark.network
class TestDownloadMode:
    """Test behavior when install.sh is run outside the repo."""

    def test_detects_download_mode(self, tmp_path: Path) -> None:
        """When run from outside the repo, enters download mode."""
        # Copy only install.sh to an isolated directory
        isolated_dir = tmp_path / "isolated"
        isolated_dir.mkdir()
        isolated_install = isolated_dir / "install.sh"
        isolated_install.write_text(INSTALL_SH.read_text())
        isolated_install.chmod(0o755)

        bin_dir = tmp_path / "bin"
        result = subprocess.run(
            ["/bin/sh", str(isolated_install), "--prefix", str(bin_dir), "--no-skill"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "Downloading from GitHub" in result.stdout
        assert (bin_dir / "term-cli").exists()
        assert (bin_dir / "term-assist").exists()

    def test_download_mode_hint_shows_curl(self, tmp_path: Path) -> None:
        """In download mode, hints use curl commands instead of ./install.sh."""
        isolated_dir = tmp_path / "isolated"
        isolated_dir.mkdir()
        isolated_install = isolated_dir / "install.sh"
        isolated_install.write_text(INSTALL_SH.read_text())
        isolated_install.chmod(0o755)

        bin_dir = tmp_path / "bin"
        result = subprocess.run(
            ["/bin/sh", str(isolated_install), "--prefix", str(bin_dir), "--no-skill"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "curl -fsSL" in result.stdout

    def test_download_mode_with_skills(self, tmp_path: Path) -> None:
        """Download mode fetches and installs skill files."""
        isolated_dir = tmp_path / "isolated"
        isolated_dir.mkdir()
        isolated_install = isolated_dir / "install.sh"
        isolated_install.write_text(INSTALL_SH.read_text())
        isolated_install.chmod(0o755)

        bin_dir = tmp_path / "bin"
        home = tmp_path / "home"
        home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)

        result = subprocess.run(
            ["/bin/sh", str(isolated_install), "--prefix", str(bin_dir), "--skill", "opencode"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        assert result.returncode == 0
        assert "Downloaded SKILL.md" in result.stdout
        assert (home / ".config/opencode/skills/term-cli/SKILL.md").exists()


# ── Summary output ─────────────────────────────────────────────────────


class TestSummary:
    """Test the summary output at the end of install."""

    def test_shows_uninstall_hint(self, tmp_path: Path) -> None:
        """Summary includes uninstall instructions."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "To uninstall:" in result.stdout
        assert "--uninstall" in result.stdout

    def test_uninstall_hint_includes_prefix(self, tmp_path: Path) -> None:
        """Uninstall hint includes the --prefix that was used."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert f"--prefix {bin_dir}" in result.stdout

    def test_done_message(self, tmp_path: Path) -> None:
        """Shows a done message with the install directory."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "Done!" in result.stdout
        assert str(bin_dir) in result.stdout

    def test_uninstall_done_message(self, tmp_path: Path) -> None:
        """Uninstall shows a done message."""
        bin_dir = tmp_path / "bin"
        run_installer("--prefix", str(bin_dir), "--no-skill")
        result = run_installer("--uninstall", "--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "has been uninstalled" in result.stdout

    def test_local_mode_hint_shows_dotslash(self, tmp_path: Path) -> None:
        """In local mode, hints use ./install.sh commands."""
        bin_dir = tmp_path / "bin"
        result = run_installer("--prefix", str(bin_dir), "--no-skill")
        assert result.returncode == 0
        assert "./install.sh" in result.stdout
