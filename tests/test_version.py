"""Tests for project version consistency and CLI reporting."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from conftest import TERM_ASSIST, TERM_CLI

ROOT = Path(__file__).parent.parent
VERSION = (ROOT / "VERSION").read_text().strip()
PRERELEASE_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    rf"(?:-{PRERELEASE_ID}(?:\.{PRERELEASE_ID})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _embedded_version(path: Path) -> str:
    match = re.search(r'^__version__ = "([^"]+)"$', path.read_text(), re.MULTILINE)
    assert match is not None, f"No __version__ found in {path.name}"
    return match.group(1)


def test_version_is_semver() -> None:
    assert SEMVER.fullmatch(VERSION)


@pytest.mark.parametrize(
    "version",
    ["1.0.0", "1.2.3-rc.1", "1.2.3-0", "1.2.3+linux-x86", "1.2.3-rc.1+build.5"],
)
def test_valid_semver_examples(version: str) -> None:
    assert SEMVER.fullmatch(version)


@pytest.mark.parametrize(
    "version",
    ["v1.0.0", "01.0.0", "1.02.0", "1.0.03", "1.0.0-01", "1.0", "1.0.0-"],
)
def test_invalid_semver_examples(version: str) -> None:
    assert SEMVER.fullmatch(version) is None


def test_embedded_versions_match_source_of_truth() -> None:
    assert _embedded_version(TERM_CLI) == VERSION
    assert _embedded_version(TERM_ASSIST) == VERSION


def test_version_flags() -> None:
    for executable in (TERM_CLI, TERM_ASSIST):
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == f"{executable.name} {VERSION}"
        assert result.stderr == ""
