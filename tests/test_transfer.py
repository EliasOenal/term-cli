"""
Tests for upload and download commands.

All tests use local tmux sessions (no SSH). The session's shell acts as
the "remote" — files are written to/read from tmp_path on the local
filesystem, exercising the full transfer pipeline (base64, gzip
compression, hash verification) without network dependencies.
"""

from __future__ import annotations

import hashlib
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Generator

import pytest

from conftest import (
    TERM_CLI,
    RunResult,
    cleanup_session,
    unique_session_name,
    wait_for_prompt,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def transfer_session(
    term_cli: Callable[..., RunResult],
    tmux_socket: str,
    tmp_path: Path,
) -> Generator[str, None, None]:
    """Session that starts with cwd=tmp_path, so uploaded files land there."""
    name = unique_session_name()
    term_cli("start", "-s", name, "-c", str(tmp_path), check=True)
    assert wait_for_prompt(term_cli, name, timeout=10)
    yield name
    cleanup_session(tmux_socket, name, term_cli)


# ---------------------------------------------------------------------------
# Upload tests
# ---------------------------------------------------------------------------

class TestUpload:
    """Tests for term-cli upload."""

    def test_upload_text(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload a text file and verify it arrives correctly."""
        local = tmp_path / "hello.txt"
        local.write_text("Hello, world!\nLine two.\n")

        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "uploaded.txt",
            "-t", "5",
            check=True,
        )
        assert "Uploaded" in result.stdout

        # Verify file appeared in session's cwd (which is tmp_path)
        remote = tmp_path / "uploaded.txt"
        assert remote.exists()
        assert remote.read_text() == "Hello, world!\nLine two.\n"

    def test_upload_binary(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload binary data and verify hash matches."""
        local = tmp_path / "data.bin"
        data = bytes(range(256)) * 40  # 10KB of binary data
        local.write_bytes(data)

        term_cli(
            "upload", "-s", transfer_session,
            str(local), "data_copy.bin",
            "-t", "5",
            check=True,
        )

        remote = tmp_path / "data_copy.bin"
        assert remote.exists()
        assert hashlib.sha256(remote.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_upload_no_overwrite(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload refuses to overwrite existing remote file without --force."""
        local = tmp_path / "src.txt"
        local.write_text("source data")

        # Pre-create the remote file
        existing = tmp_path / "exists.txt"
        existing.write_text("old data")

        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "exists.txt",
            "-t", "5",
        )
        assert result.returncode == 2
        assert "already exists" in result.stderr.lower() or "force" in result.stderr.lower()
        # Original should be untouched
        assert existing.read_text() == "old data"

    def test_upload_force_overwrite(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload overwrites with --force."""
        local = tmp_path / "src.txt"
        local.write_text("new data")

        existing = tmp_path / "exists2.txt"
        existing.write_text("old data")

        term_cli(
            "upload", "-s", transfer_session,
            str(local), "exists2.txt",
            "-f", "-t", "5",
            check=True,
        )
        assert existing.read_text() == "new data"

    def test_upload_missing_local(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
    ) -> None:
        """Upload fails with clear error for missing local file."""
        result = term_cli(
            "upload", "-s", transfer_session,
            "/nonexistent/path/file.txt",
            "-t", "5",
        )
        assert result.returncode == 2
        assert "does not exist" in result.stderr.lower()

    def test_upload_default_remote_path(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Omitting REMOTE_PATH uses basename of local file."""
        # Create the source file in a subdirectory so it doesn't collide
        # with the remote destination (the session's cwd is tmp_path).
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        local = src_dir / "autoname.txt"
        local.write_text("auto")

        term_cli(
            "upload", "-s", transfer_session,
            str(local),
            "-t", "5",
            check=True,
        )

        # Should land as "autoname.txt" in the session's cwd
        remote = tmp_path / "autoname.txt"
        assert remote.exists()
        assert remote.read_text() == "auto"

    def test_upload_larger_file(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload ~50KB file to verify the paste mechanism at scale."""
        local = tmp_path / "large.bin"
        data = os.urandom(50 * 1024)
        local.write_bytes(data)

        term_cli(
            "upload", "-s", transfer_session,
            str(local), "large_copy.bin",
            "-t", "5",
            check=True,
        )

        remote = tmp_path / "large_copy.bin"
        assert remote.exists()
        assert hashlib.sha256(remote.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Download tests
# ---------------------------------------------------------------------------

class TestDownload:
    """Tests for term-cli download."""

    def test_download_text(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download a text file and verify contents."""
        # Create a file in the session's cwd
        remote = tmp_path / "greeting.txt"
        remote.write_text("Hello from remote!\n")

        local_dest = tmp_path / "dl_greeting.txt"
        term_cli(
            "download", "-s", transfer_session,
            "greeting.txt", str(local_dest),
            "-t", "5",
            check=True,
        )

        assert local_dest.exists()
        assert local_dest.read_text() == "Hello from remote!\n"

    def test_download_binary(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download binary data and verify hash."""
        remote = tmp_path / "binary.dat"
        data = bytes(range(256)) * 40
        remote.write_bytes(data)

        local_dest = tmp_path / "dl_binary.dat"
        term_cli(
            "download", "-s", transfer_session,
            "binary.dat", str(local_dest),
            "-t", "5",
            check=True,
        )

        assert local_dest.exists()
        assert hashlib.sha256(local_dest.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_download_no_overwrite(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download refuses to overwrite existing local file without --force."""
        remote = tmp_path / "remote.txt"
        remote.write_text("remote data")

        local_dest = tmp_path / "dl_existing.txt"
        local_dest.write_text("local data")

        result = term_cli(
            "download", "-s", transfer_session,
            "remote.txt", str(local_dest),
            "-t", "5",
        )
        assert result.returncode == 2
        assert "already exists" in result.stderr.lower() or "force" in result.stderr.lower()
        assert local_dest.read_text() == "local data"

    def test_download_force_overwrite(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download overwrites with --force."""
        remote = tmp_path / "remote2.txt"
        remote.write_text("fresh data")

        local_dest = tmp_path / "dl_overwrite.txt"
        local_dest.write_text("stale")

        term_cli(
            "download", "-s", transfer_session,
            "remote2.txt", str(local_dest),
            "-f", "-t", "5",
            check=True,
        )
        assert local_dest.read_text() == "fresh data"

    def test_download_missing_remote(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download fails with clear error for missing remote file."""
        result = term_cli(
            "download", "-s", transfer_session,
            "does_not_exist.txt",
            str(tmp_path / "nope.txt"),
            "-t", "5",
        )
        assert result.returncode == 2
        assert "does not exist" in result.stderr.lower()

    def test_download_default_local_path(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Omitting LOCAL_PATH downloads to basename in agent's cwd."""
        remote = tmp_path / "autodown.txt"
        remote.write_text("auto download")

        # Run term-cli from a *different* directory so the default basename
        # resolves there (not in tmp_path where the remote file lives).
        dest_dir = tmp_path / "dl_dest"
        dest_dir.mkdir()

        result = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "download", "-s", transfer_session,
                "autodown.txt",  # no LOCAL_PATH => basename in cwd
                "-t", "5",
            ],
            capture_output=True,
            text=True,
            cwd=str(dest_dir),
        )
        assert result.returncode == 0, (
            f"download failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        landed = dest_dir / "autodown.txt"
        assert landed.exists(), f"File not found at {landed}"
        assert landed.read_text() == "auto download"


# ---------------------------------------------------------------------------
# Roundtrip tests
# ---------------------------------------------------------------------------

class TestTransferRoundtrip:
    """Upload then download, verify identical."""

    def test_roundtrip_text(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        local_src = tmp_path / "rt_src.txt"
        content = "Round-trip test!\nSpecial chars: $HOME 'quotes' \"double\" \\back\n"
        local_src.write_text(content)

        term_cli(
            "upload", "-s", transfer_session,
            str(local_src), "rt_remote.txt",
            "-t", "5",
            check=True,
        )

        local_dst = tmp_path / "rt_dst.txt"
        term_cli(
            "download", "-s", transfer_session,
            "rt_remote.txt", str(local_dst),
            "-t", "5",
            check=True,
        )

        assert local_dst.read_text() == content

    def test_roundtrip_binary(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        local_src = tmp_path / "rt_src.bin"
        data = os.urandom(20 * 1024)  # 20KB
        local_src.write_bytes(data)

        term_cli(
            "upload", "-s", transfer_session,
            str(local_src), "rt_remote.bin",
            "-t", "5",
            check=True,
        )

        local_dst = tmp_path / "rt_dst.bin"
        term_cli(
            "download", "-s", transfer_session,
            "rt_remote.bin", str(local_dst),
            "-t", "5",
            check=True,
        )

        assert hashlib.sha256(local_dst.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Strategy persistence tests
# ---------------------------------------------------------------------------

class TestDownloadStrategy:
    """Test download strategy detection and persistence."""

    def test_strategy_persistence(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Verify @term_cli_dl_strategy is saved and remembered."""
        # Set strategy to chunked via tmux option
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={transfer_session}:",
             "@term_cli_dl_strategy", "chunked"],
            capture_output=True,
            check=True,
        )

        # Create a remote file
        remote = tmp_path / "strat.txt"
        remote.write_text("strategy test\n")

        local_dest = tmp_path / "dl_strat.txt"
        result = term_cli(
            "download", "-s", transfer_session,
            "strat.txt", str(local_dest),
            "-v", "-t", "5",
            check=True,
        )

        # Should have used chunked strategy (verbose output says so)
        assert "chunked" in result.stderr.lower()
        assert local_dest.read_text() == "strategy test\n"

    def test_chunked_download_works(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Force chunked strategy and verify correct download."""
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={transfer_session}:",
             "@term_cli_dl_strategy", "chunked"],
            capture_output=True,
            check=True,
        )

        remote = tmp_path / "chunk_data.bin"
        data = os.urandom(5 * 1024)  # 5KB — multiple chunks at 80x24
        remote.write_bytes(data)

        local_dest = tmp_path / "dl_chunk.bin"
        term_cli(
            "download", "-s", transfer_session,
            "chunk_data.bin", str(local_dest),
            "-v", "-t", "5",
            check=True,
        )

        assert hashlib.sha256(local_dest.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Edge case tests — empty files, locked sessions, special filenames
# ---------------------------------------------------------------------------

class TestTransferEdgeCases:
    """Tests for edge cases in upload/download."""

    def test_upload_empty_file_rejected(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload rejects empty files with exit code 2."""
        local = tmp_path / "empty.txt"
        local.write_bytes(b"")

        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "empty_remote.txt",
            "-t", "5",
        )
        assert result.returncode == 2
        assert "empty" in result.stderr.lower()

    def test_upload_locked_session(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Upload to locked session returns exit code 5."""
        name = unique_session_name()
        try:
            term_cli("start", "-s", name, "-c", str(tmp_path), "-l", check=True)
            assert wait_for_prompt(term_cli, name, timeout=10)

            local = tmp_path / "locked_test.txt"
            local.write_text("should not upload")

            result = term_cli(
                "upload", "-s", name,
                str(local), "nope.txt",
                "-t", "5",
            )
            assert result.returncode == 5
            assert "locked" in result.stderr.lower()
        finally:
            # Unlock before cleanup
            subprocess.run(
                ["tmux", "-L", tmux_socket, "set-option", "-t", f"={name}:",
                 "-u", "@term_cli_agent_locked"],
                capture_output=True,
            )
            term_cli("kill", "-s", name)

    def test_download_locked_session(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Download from locked session returns exit code 5."""
        name = unique_session_name()
        try:
            term_cli("start", "-s", name, "-c", str(tmp_path), "-l", check=True)
            assert wait_for_prompt(term_cli, name, timeout=10)

            remote = tmp_path / "locked_dl.txt"
            remote.write_text("secret")

            result = term_cli(
                "download", "-s", name,
                "locked_dl.txt", str(tmp_path / "dl_locked.txt"),
                "-t", "5",
            )
            assert result.returncode == 5
            assert "locked" in result.stderr.lower()
        finally:
            subprocess.run(
                ["tmux", "-L", tmux_socket, "set-option", "-t", f"={name}:",
                 "-u", "@term_cli_agent_locked"],
                capture_output=True,
            )
            term_cli("kill", "-s", name)

    def test_upload_filename_with_spaces(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload a file with spaces in remote filename."""
        local = tmp_path / "spaces.txt"
        local.write_text("file with spaces test\n")

        term_cli(
            "upload", "-s", transfer_session,
            str(local), "file with spaces.txt",
            "-t", "5",
            check=True,
        )

        remote = tmp_path / "file with spaces.txt"
        assert remote.exists()
        assert remote.read_text() == "file with spaces test\n"

    def test_download_filename_with_spaces(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download a file with spaces in remote filename."""
        remote = tmp_path / "dl spaces test.txt"
        remote.write_text("spaced download\n")

        local_dest = tmp_path / "dl_spaced.txt"
        term_cli(
            "download", "-s", transfer_session,
            "dl spaces test.txt", str(local_dest),
            "-t", "5",
            check=True,
        )

        assert local_dest.read_text() == "spaced download\n"

    def test_upload_filename_with_quotes(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload with single quotes in remote filename."""
        local = tmp_path / "quoted.txt"
        local.write_text("quoted test\n")

        term_cli(
            "upload", "-s", transfer_session,
            str(local), "it's-a-file.txt",
            "-t", "5",
            check=True,
        )

        remote = tmp_path / "it's-a-file.txt"
        assert remote.exists()
        assert remote.read_text() == "quoted test\n"

    def test_download_filename_with_quotes(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download with single quotes in remote filename."""
        remote = tmp_path / "o'reilly.txt"
        remote.write_text("quoted dl\n")

        local_dest = tmp_path / "dl_quoted.txt"
        term_cli(
            "download", "-s", transfer_session,
            "o'reilly.txt", str(local_dest),
            "-t", "5",
            check=True,
        )

        assert local_dest.read_text() == "quoted dl\n"

    def test_upload_nonexistent_session(
        self,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload to nonexistent session fails with exit code 2."""
        local = tmp_path / "orphan.txt"
        local.write_text("nowhere to go")

        result = term_cli(
            "upload", "-s", "does_not_exist_session",
            str(local), "nope.txt",
            "-t", "5",
        )
        assert result.returncode == 2
        assert "does not exist" in result.stderr.lower()

    def test_download_nonexistent_session(
        self,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download from nonexistent session fails with exit code 2."""
        result = term_cli(
            "download", "-s", "does_not_exist_session",
            "nope.txt", str(tmp_path / "nope.txt"),
            "-t", "5",
        )
        assert result.returncode == 2
        assert "does not exist" in result.stderr.lower()

    def test_download_parent_dir_missing(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download to a local path with missing parent dir fails with exit 2."""
        remote = tmp_path / "exists.txt"
        remote.write_text("data")

        result = term_cli(
            "download", "-s", transfer_session,
            "exists.txt", str(tmp_path / "no_such_dir" / "file.txt"),
            "-t", "5",
        )
        assert result.returncode == 2
        assert "parent directory" in result.stderr.lower() or "does not exist" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Hash verification edge cases
# ---------------------------------------------------------------------------

class TestHashVerification:
    """Tests for hash verification behavior during transfers."""

    def test_upload_hash_verified(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload with verbose shows hash verification succeeded."""
        local = tmp_path / "hash_test.txt"
        local.write_text("verify this content\n")

        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "hash_verified.txt",
            "-v", "-t", "5",
            check=True,
        )
        # Verbose output should show hash verification
        assert "hash verified" in result.stderr.lower()

    def test_download_hash_verified(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download with verbose shows hash verification succeeded."""
        remote = tmp_path / "dl_hash_test.txt"
        remote.write_text("download hash test\n")

        local_dest = tmp_path / "dl_hash_out.txt"
        result = term_cli(
            "download", "-s", transfer_session,
            "dl_hash_test.txt", str(local_dest),
            "-v", "-t", "5",
            check=True,
        )
        assert "hash verified" in result.stderr.lower()




# ---------------------------------------------------------------------------
# Download fallback tests
# ---------------------------------------------------------------------------

class TestDownloadFallback:
    """Tests for download strategy selection and fallback behavior."""

    def test_remembered_chunked_skips_pipe_pane(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """When strategy is remembered as chunked, pipe-pane is not attempted."""
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={transfer_session}:",
             "@term_cli_dl_strategy", "chunked"],
            capture_output=True,
            check=True,
        )

        remote = tmp_path / "skip_pipe.txt"
        remote.write_text("skip pipe-pane\n")

        local_dest = tmp_path / "dl_skip_pipe.txt"
        result = term_cli(
            "download", "-s", transfer_session,
            "skip_pipe.txt", str(local_dest),
            "-v", "-t", "5",
            check=True,
        )

        assert "chunked" in result.stderr.lower()
        assert "pipe-pane" not in result.stderr.lower()
        assert local_dest.read_text() == "skip pipe-pane\n"

    def test_first_download_tries_pipe_pane(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """First download (no remembered strategy) tries pipe-pane first."""
        # Ensure no strategy is set (clear any leftover)
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={transfer_session}:",
             "-u", "@term_cli_dl_strategy"],
            capture_output=True,
        )

        remote = tmp_path / "pipe_first.txt"
        remote.write_text("try pipe first\n")

        local_dest = tmp_path / "dl_pipe_first.txt"
        result = term_cli(
            "download", "-s", transfer_session,
            "pipe_first.txt", str(local_dest),
            "-v", "-t", "5",
            check=True,
        )

        # Verbose output should mention pipe-pane attempt
        assert "pipe-pane" in result.stderr.lower()
        assert local_dest.read_text() == "try pipe first\n"

    def test_pipe_fault_injection_falls_back_to_chunked(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Injected pipe payload loss should trigger chunked fallback and succeed."""
        subprocess.run(
            [
                "tmux", "-L", tmux_socket, "set-option", "-t", f"={transfer_session}:",
                "-u", "@term_cli_dl_strategy",
            ],
            capture_output=True,
        )

        remote = tmp_path / "pipe_fault.bin"
        # Incompressible-ish data so we get plenty of base64 lines to drop.
        remote.write_bytes(os.urandom(512 * 1024))
        expected_sha = hashlib.sha256(remote.read_bytes()).hexdigest()

        local_dest = tmp_path / "dl_pipe_fault.bin"
        env = {
            **os.environ,
            "TERM_CLI_TEST_HOOKS": "1",
            "TERM_CLI_TEST_PIPE_DROP_BLOCK": "12:220",
        }
        proc = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "download", "-s", transfer_session,
                "pipe_fault.bin", str(local_dest),
                "-v", "-t", "20",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=40,
        )

        assert proc.returncode == 0, (
            f"download failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        stderr = proc.stderr.lower()
        assert "trying pipe-pane" in stderr
        assert "switching to chunked" in stderr
        assert local_dest.exists()
        assert hashlib.sha256(local_dest.read_bytes()).hexdigest() == expected_sha


# ---------------------------------------------------------------------------
# Prompt readiness tests
# ---------------------------------------------------------------------------

class TestPromptReadiness:
    """Tests that upload/download refuse to run when the session is not ready."""

    def test_upload_refused_when_command_running(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload fails when a command is running (not at prompt)."""
        local = tmp_path / "ready_test.txt"
        local.write_text("test data")

        # Start a long-running command
        term_cli("run", "-s", transfer_session, "sleep 30")
        time.sleep(0.5)

        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "should_not_exist.txt",
            "-t", "5",
        )
        assert result.returncode == 2
        assert "not at a prompt" in result.stderr.lower()

        # Clean up the running command
        term_cli("send-key", "-s", transfer_session, "C-c")
        assert wait_for_prompt(term_cli, transfer_session, timeout=10)

    def test_download_refused_when_command_running(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download fails when a command is running (not at prompt)."""
        remote = tmp_path / "dl_ready.txt"
        remote.write_text("download me\n")

        # Start a long-running command
        term_cli("run", "-s", transfer_session, "sleep 30")
        time.sleep(0.5)

        local_dest = tmp_path / "dl_ready_local.txt"
        result = term_cli(
            "download", "-s", transfer_session,
            "dl_ready.txt", str(local_dest),
            "-t", "5",
        )
        assert result.returncode == 2
        assert "not at a prompt" in result.stderr.lower()

        # Clean up
        term_cli("send-key", "-s", transfer_session, "C-c")
        assert wait_for_prompt(term_cli, transfer_session, timeout=10)

    def test_upload_refused_on_alt_screen(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload fails when session is on alternate screen (TUI running)."""
        local = tmp_path / "alt_test.txt"
        local.write_text("test data")

        # Launch vi (always uses alt-screen)
        vi_target = tmp_path / "vi_target.txt"
        vi_target.write_text("x\n")
        term_cli("run", "-s", transfer_session, f"vi {vi_target}")
        from conftest import wait_for_idle
        wait_for_idle(term_cli, transfer_session, idle_seconds=1.0, timeout=5)

        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "should_not_exist.txt",
            "-t", "5",
        )
        assert result.returncode == 2
        assert "not at a prompt" in result.stderr.lower()

        # Exit vi
        term_cli("send-text", "-s", transfer_session, ":q!")
        term_cli("send-key", "-s", transfer_session, "Enter")
        assert wait_for_prompt(term_cli, transfer_session, timeout=10)

    def test_download_refused_on_alt_screen(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download fails when session is on alternate screen."""
        remote = tmp_path / "alt_dl.txt"
        remote.write_text("download me\n")

        # Launch vi (always uses alt-screen)
        vi_target = tmp_path / "vi_target2.txt"
        vi_target.write_text("x\n")
        term_cli("run", "-s", transfer_session, f"vi {vi_target}")
        from conftest import wait_for_idle
        wait_for_idle(term_cli, transfer_session, idle_seconds=1.0, timeout=5)

        local_dest = tmp_path / "alt_dl_local.txt"
        result = term_cli(
            "download", "-s", transfer_session,
            "alt_dl.txt", str(local_dest),
            "-t", "5",
        )
        assert result.returncode == 2
        assert "not at a prompt" in result.stderr.lower()

        # Exit vi
        term_cli("send-text", "-s", transfer_session, ":q!")
        term_cli("send-key", "-s", transfer_session, "Enter")
        assert wait_for_prompt(term_cli, transfer_session, timeout=10)


# ---------------------------------------------------------------------------
# Terminal cleanliness tests
# ---------------------------------------------------------------------------

# Substrings that must never appear on the visible screen after a transfer.
_ARTIFACTS = [
    "HISTCONTROL",
    "_TCH",
    "set +o history",
    "set -o history",
    "stty ",
    "printf '\\033",
    "TC_READY",
    "TC_DONE",
    "TC_ERR",
    "TC_NOWRITE",
    "TC_DL_BEGIN",
    "TC_DL_END",
    "TC_DL_INFO",
    "TC_C ",
    "TC_E ",
    "TC_PY3_",
    "TC_PYBIN_",
    "TC_PY_DONE",
    "TC_CHK",
    "TC_FE_",
    "import base64",
    "import gzip",
    "import hashlib",
    "python3 -c",
    "python -c",
    "/dev/tty",
    "1049h",
    "1049l",
]


def _screen_has_artifacts(screen: str) -> list[str]:
    """Return list of artifact substrings found on screen."""
    return [a for a in _ARTIFACTS if a in screen]


def _count_prompt_lines(screen: str) -> int:
    """Count lines that end with a prompt character ($, #, %)."""
    count = 0
    for line in screen.splitlines():
        stripped = line.rstrip()
        if stripped and any(
            stripped.endswith(s)
            for s in ("$", "$ ", "#", "# ", "%", "% ")
        ):
            count += 1
    return count


def _assert_clean(
    term_cli: Callable[..., RunResult],
    session: str,
    context: str,
    prompts_before: int | None = None,
    max_new_prompts: int = 1,
) -> None:
    """Assert screen is clean, echo works, and not on alt-screen."""
    screen = term_cli("capture", "-s", session).stdout
    found = _screen_has_artifacts(screen)
    assert not found, f"Artifacts {context}: {found}\n{screen}"

    if prompts_before is not None:
        prompts_after = _count_prompt_lines(screen)
        assert prompts_after <= prompts_before + max_new_prompts, (
            f"Too many prompts {context}: "
            f"before={prompts_before}, after={prompts_after}\n{screen}"
        )

    status = term_cli("status", "-s", session, check=True)
    assert "Screen: normal" in status.stdout, (
        f"Stuck on alt-screen {context}\n{status.stdout}"
    )

    marker = f"_CK_{os.getpid()}_{time.monotonic_ns() % 10**9}"
    term_cli("run", "-s", session, f"echo {marker}", "-w", "-t", "5", check=True)
    screen = term_cli("capture", "-s", session).stdout
    assert marker in screen, f"Echo broken {context}\n{screen}"


class TestTerminalCleanliness:
    """Verify transfers leave the terminal in a clean, usable state.

    Local source files for uploads are created in ``tmp_path / "local"`` to
    avoid colliding with the session's CWD (which is ``tmp_path``).  Without
    this separation, writing ``tmp_path / "foo.txt"`` locally makes the
    remote ``_remote_file_exists`` check find the file, causing
    "already exists" errors even on the first upload.
    """

    @staticmethod
    def _local_dir(tmp_path: Path) -> Path:
        d = tmp_path / "local"
        d.mkdir(exist_ok=True)
        return d

    # -- upload happy path --

    def test_upload_leaves_clean_screen(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """No artifacts, usable prompt, normal screen after upload."""
        local = self._local_dir(tmp_path) / "clean_up.txt"
        local.write_text("clean test\n")
        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )

        term_cli(
            "upload", "-s", transfer_session,
            str(local), "clean_up.txt", "-t", "5",
            check=True,
        )
        _assert_clean(term_cli, transfer_session, "after upload",
                      prompts_before=prompts)

    def test_upload_force_leaves_clean_screen(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload with --force (overwriting existing file) leaves terminal clean."""
        local = self._local_dir(tmp_path) / "force_up.txt"
        local.write_text("overwritten\n")

        # Pre-create the remote file directly (avoids a full upload round-trip)
        (tmp_path / "force_up.txt").write_text("original\n")

        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )
        term_cli(
            "upload", "-s", transfer_session,
            str(local), "force_up.txt", "--force", "-t", "5",
            check=True,
        )
        _assert_clean(term_cli, transfer_session, "after --force upload",
                      prompts_before=prompts)
        assert (tmp_path / "force_up.txt").read_text() == "overwritten\n"

    # -- download happy path (pipe-pane) --

    def test_download_pipe_leaves_clean_screen(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Pipe-pane download leaves terminal clean."""
        remote = tmp_path / "clean_pipe.txt"
        remote.write_text("pipe-pane test\n")
        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )

        local_dest = self._local_dir(tmp_path) / "clean_pipe_local.txt"
        term_cli(
            "download", "-s", transfer_session,
            str(remote), str(local_dest), "-t", "5",
            check=True,
        )
        _assert_clean(term_cli, transfer_session, "after pipe-pane download",
                      prompts_before=prompts)

    # -- download happy path (chunked) --

    def test_download_chunked_leaves_clean_screen(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Forced-chunked download leaves terminal clean."""
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={transfer_session}:",
             "@term_cli_dl_strategy", "chunked"],
            capture_output=True, check=True,
        )

        remote = tmp_path / "clean_chunk.bin"
        remote.write_bytes(os.urandom(3 * 1024))

        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )

        local_dest = self._local_dir(tmp_path) / "clean_chunk_local.bin"
        term_cli(
            "download", "-s", transfer_session,
            str(remote), str(local_dest), "-t", "5",
            check=True,
        )
        _assert_clean(term_cli, transfer_session, "after chunked download",
                      prompts_before=prompts)

    def test_sequential_uploads_no_accumulation(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Back-to-back uploads must not accumulate artifacts or prompts."""
        local_dir = self._local_dir(tmp_path)
        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )

        for i in range(2):
            f = local_dir / f"seq_{i}.txt"
            f.write_text(f"file {i}\n")
            term_cli(
                "upload", "-s", transfer_session,
                str(f), f"seq_{i}.txt", "-t", "5",
                check=True,
            )

        _assert_clean(term_cli, transfer_session,
                      "after 2 sequential uploads",
                      prompts_before=prompts, max_new_prompts=2)

    def test_sequential_downloads_no_accumulation(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Back-to-back downloads must not accumulate artifacts."""
        local_dir = self._local_dir(tmp_path)
        for i in range(2):
            (tmp_path / f"seq_dl_{i}.txt").write_text(f"dl {i}\n")

        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )

        for i in range(2):
            term_cli(
                "download", "-s", transfer_session,
                str(tmp_path / f"seq_dl_{i}.txt"),
                str(local_dir / f"seq_dl_{i}_local.txt"),
                "-t", "5", check=True,
            )

        _assert_clean(term_cli, transfer_session,
                      "after 2 sequential downloads",
                      prompts_before=prompts, max_new_prompts=2)

    def test_mixed_upload_download_sequence(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Interleaved upload then download keeps terminal clean."""
        local_dir = self._local_dir(tmp_path)
        local = local_dir / "mix.txt"
        local.write_text("mixed transfer\n")

        # Upload
        term_cli(
            "upload", "-s", transfer_session,
            str(local), "mix.txt", "-t", "5",
            check=True,
        )
        # Download back
        term_cli(
            "download", "-s", transfer_session,
            str(tmp_path / "mix.txt"),
            str(local_dir / "mix_back.txt"),
            "-t", "5", check=True,
        )

        _assert_clean(term_cli, transfer_session,
                      "after mixed upload/download sequence")

    # -- error paths --

    def test_terminal_usable_after_overwrite_refused(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """After upload refused (file exists, no --force), terminal is clean."""
        local_dir = self._local_dir(tmp_path)
        local = local_dir / "refuse.txt"
        local.write_text("first\n")

        # Pre-create the remote file directly (avoids a full upload round-trip)
        (tmp_path / "refuse.txt").write_text("existing\n")

        # Attempt upload without --force
        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "refuse.txt", "-t", "5",
        )
        assert result.returncode == 2

        _assert_clean(term_cli, transfer_session,
                      "after upload overwrite refused")

    def test_terminal_usable_after_missing_remote_file(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """After download of nonexistent file, terminal is clean."""
        local_dir = self._local_dir(tmp_path)
        result = term_cli(
            "download", "-s", transfer_session,
            "/no/such/file.txt",
            str(local_dir / "ghost.txt"),
            "-t", "5",
        )
        assert result.returncode != 0

        _assert_clean(term_cli, transfer_session,
                      "after download of nonexistent file")

    def test_terminal_usable_after_success_fail_success(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Fail -> success sequence keeps terminal working."""
        local_dir = self._local_dir(tmp_path)

        # Fail: download nonexistent file
        result = term_cli(
            "download", "-s", transfer_session,
            "/no/such/sfs.txt",
            str(local_dir / "sfs_ghost.txt"),
            "-t", "5",
        )
        assert result.returncode != 0

        # Success: upload after failure
        local = local_dir / "sfs.txt"
        local.write_text("still works\n")
        term_cli(
            "upload", "-s", transfer_session,
            str(local), "sfs.txt", "-t", "5",
            check=True,
        )

        _assert_clean(term_cli, transfer_session,
                      "after fail->success transfer")
        assert (tmp_path / "sfs.txt").read_text() == "still works\n"

    def test_terminal_usable_after_missing_file_with_chunked_strategy(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Missing-file error (before strategy selection) still restores
        terminal even when the chunked strategy is remembered.

        Note: the file-existence check runs on alt-screen *before* strategy
        selection, so the chunked code path is never reached.  This test
        verifies the pre-strategy error path is clean with a strategy set.
        """
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={transfer_session}:",
             "@term_cli_dl_strategy", "chunked"],
            capture_output=True, check=True,
        )

        local_dir = self._local_dir(tmp_path)
        result = term_cli(
            "download", "-s", transfer_session,
            "/no/such/chunked.txt",
            str(local_dir / "ghost_chunk.txt"),
            "-t", "5",
        )
        assert result.returncode != 0

        _assert_clean(term_cli, transfer_session,
                      "after failed chunked download")


# ---------------------------------------------------------------------------
# Error path tests — TC_NOWRITE, unwritable paths, and terminal recovery
# ---------------------------------------------------------------------------

class TestErrorPaths:
    """Tests for transfer error paths that exercise helper dismissal."""

    def test_upload_to_unwritable_directory(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload to a read-only directory triggers TC_NOWRITE and exit 2."""
        local_dir = tmp_path / "local"
        local_dir.mkdir(exist_ok=True)
        local = local_dir / "nowrite.txt"
        local.write_text("cannot write\n")

        # Create a read-only directory in the session's cwd
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        readonly.chmod(0o555)

        try:
            # -t 10: ready_timeout = min(10, 30) = 10s before TC_NOWRITE check
            result = term_cli(
                "upload", "-s", transfer_session,
                str(local), "readonly/nowrite.txt",
                "-t", "5",
                timeout=15.0,
            )
            assert result.returncode == 2, (
                f"Expected exit 2, got {result.returncode}: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            assert "cannot write" in result.stderr.lower() or "permission" in result.stderr.lower(), (
                f"Expected permission error in stderr: {result.stderr!r}"
            )
        finally:
            readonly.chmod(0o755)

    def test_upload_to_unwritable_directory_leaves_clean_terminal(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """TC_NOWRITE path dismisses helper and leaves terminal usable."""
        local_dir = tmp_path / "local"
        local_dir.mkdir(exist_ok=True)
        local = local_dir / "nowrite2.txt"
        local.write_text("cannot write\n")

        readonly = tmp_path / "readonly2"
        readonly.mkdir()
        readonly.chmod(0o555)

        try:
            prompts = _count_prompt_lines(
                term_cli("capture", "-s", transfer_session).stdout
            )
            term_cli(
                "upload", "-s", transfer_session,
                str(local), "readonly2/nowrite2.txt",
                "-t", "5",
                timeout=15.0,
            )
            _assert_clean(term_cli, transfer_session,
                          "after TC_NOWRITE upload", prompts_before=prompts)
        finally:
            readonly.chmod(0o755)

    def test_upload_to_nonexistent_remote_directory(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Upload to a path whose parent directory doesn't exist fails cleanly."""
        local_dir = tmp_path / "local"
        local_dir.mkdir(exist_ok=True)
        local = local_dir / "orphan.txt"
        local.write_text("nowhere to go\n")

        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "no_such_dir/sub/orphan.txt",
            "-t", "5",
            timeout=30.0,
        )
        assert result.returncode != 0
        _assert_clean(term_cli, transfer_session,
                      "after upload to nonexistent remote dir")


# ---------------------------------------------------------------------------
# Empty file download
# ---------------------------------------------------------------------------

class TestEmptyFileDownload:
    """Test downloading a file with zero bytes of content."""

    def test_download_empty_remote_file(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Download an empty remote file (if supported) or get clear error."""
        remote = tmp_path / "empty_remote.txt"
        remote.write_text("")  # 0 bytes

        local_dest = tmp_path / "local" / "empty_dl.txt"
        local_dest.parent.mkdir(exist_ok=True)

        # empty files may be rejected by the download helper (b64 0 lines)
        result = term_cli(
            "download", "-s", transfer_session,
            "empty_remote.txt", str(local_dest),
            "-t", "5",
        )
        # Regardless of success or handled error, terminal must be clean
        _assert_clean(term_cli, transfer_session, "after empty file download")


# ---------------------------------------------------------------------------
# Erase exactness tests — verify transfer erases exactly what it adds
# ---------------------------------------------------------------------------

class TestEraseExactness:
    """Verify that transfers erase exactly the echoed setup command lines.

    The ``_enter_alt_echo_off`` command is echoed on the normal screen before
    entering alt-screen.  When leaving alt-screen, the erase sequence must
    remove exactly those lines — no more, no less.

    Each test:
    1. Creates a session with specific terminal width.
    2. Sets a PS1 of a specific length to control the prompt width.
    3. Fills the screen with distinctive "marker" lines.
    4. Performs an upload (triggering the erase logic).
    5. Verifies all marker lines survive on the screen.
    """

    @staticmethod
    def _make_session(
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
        cols: int,
        rows: int = 24,
        ps1: str = "$ ",
    ) -> str:
        """Create a session with specific dimensions and PS1."""
        name = unique_session_name()
        term_cli(
            "start", "-s", name,
            "-c", str(tmp_path),
            "-x", str(cols), "-y", str(rows),
            check=True,
        )
        assert wait_for_prompt(term_cli, name, timeout=10)

        # Set PS1 to control prompt width.  Use a simple non-special prompt.
        term_cli(
            "run", "-s", name,
            f"PS1='{ps1}'",
            "-w", "-t", "5",
            check=True,
        )
        return name

    @staticmethod
    def _fill_screen(
        term_cli: Callable[..., RunResult],
        session: str,
        num_markers: int = 4,
    ) -> list[str]:
        """Echo distinctive marker lines to fill the screen.

        Uses a single multi-echo command to minimize round-trips.
        """
        markers: list[str] = []
        parts: list[str] = []
        for i in range(num_markers):
            marker = f"MK_{os.getpid()}_{i}"
            markers.append(marker)
            parts.append(f"echo {marker}")
        # Run all echoes in one shot
        term_cli(
            "run", "-s", session,
            "; ".join(parts),
            "-w", "-t", "5",
            check=True,
        )
        return markers

    @staticmethod
    def _verify_markers(
        term_cli: Callable[..., RunResult],
        session: str,
        markers: list[str],
        context: str,
    ) -> None:
        """Verify all marker lines are still visible on screen (with scrollback)."""
        # Use scrollback capture to see all content including what may have
        # scrolled up during the transfer.
        screen = term_cli("capture", "-s", session, "-n", "100").stdout
        missing = [m for m in markers if m not in screen]
        assert not missing, (
            f"Markers erased {context}: {missing}\n"
            f"Screen:\n{screen}"
        )

    def test_narrow_short_prompt(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """80-col terminal, 2-char prompt: command wraps to ~2 lines."""
        session = self._make_session(term_cli, tmp_path, cols=80, ps1="$ ")
        try:
            local_dir = tmp_path / "local"
            local_dir.mkdir(exist_ok=True)
            local = local_dir / "narrow_short.txt"
            local.write_text("narrow short prompt test\n")

            markers = self._fill_screen(term_cli, session)
            term_cli(
                "upload", "-s", session,
                str(local), "narrow_short.txt", "-t", "5",
                check=True,
            )
            self._verify_markers(term_cli, session, markers,
                                 "80-col 2-char prompt")
            _assert_clean(term_cli, session, "80-col short prompt")
        finally:
            cleanup_session(tmux_socket, session, term_cli)

    def test_narrow_long_prompt(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """80-col terminal, 60-char prompt: command wraps to 2+ lines."""
        # 57 chars of path-like text + "$ " = 59 visible chars
        ps1 = "A" * 57 + "$ "
        session = self._make_session(term_cli, tmp_path, cols=80, ps1=ps1)
        try:
            local_dir = tmp_path / "local"
            local_dir.mkdir(exist_ok=True)
            local = local_dir / "narrow_long.txt"
            local.write_text("narrow long prompt test\n")

            markers = self._fill_screen(term_cli, session)
            term_cli(
                "upload", "-s", session,
                str(local), "narrow_long.txt", "-t", "5",
                check=True,
            )
            self._verify_markers(term_cli, session, markers,
                                 "80-col 59-char prompt")
            _assert_clean(term_cli, session, "80-col long prompt")
        finally:
            cleanup_session(tmux_socket, session, term_cli)

    def test_wide_terminal(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """200-col terminal, short prompt: command fits on 1 line."""
        session = self._make_session(term_cli, tmp_path, cols=200, ps1="$ ")
        try:
            local_dir = tmp_path / "local"
            local_dir.mkdir(exist_ok=True)
            local = local_dir / "wide_term.txt"
            local.write_text("wide terminal test\n")

            markers = self._fill_screen(term_cli, session)
            term_cli(
                "upload", "-s", session,
                str(local), "wide_term.txt", "-t", "5",
                check=True,
            )
            self._verify_markers(term_cli, session, markers,
                                 "200-col short prompt")
            _assert_clean(term_cli, session, "200-col wide terminal")
        finally:
            cleanup_session(tmux_socket, session, term_cli)

    def test_very_narrow_very_long_prompt(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """60-col terminal, 50-char prompt: command wraps to 3+ lines."""
        ps1 = "P" * 48 + "$ "
        session = self._make_session(term_cli, tmp_path, cols=60, ps1=ps1)
        try:
            local_dir = tmp_path / "local"
            local_dir.mkdir(exist_ok=True)
            local = local_dir / "vnarrow.txt"
            local.write_text("very narrow test\n")

            markers = self._fill_screen(term_cli, session)
            term_cli(
                "upload", "-s", session,
                str(local), "vnarrow.txt", "-t", "5",
                check=True,
            )
            self._verify_markers(term_cli, session, markers,
                                 "60-col 50-char prompt")
            _assert_clean(term_cli, session, "60-col very long prompt")
        finally:
            cleanup_session(tmux_socket, session, term_cli)

    def test_download_erase_exactness(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Download also erases exactly — tested with 80-col, long prompt."""
        ps1 = "D" * 40 + "$ "
        session = self._make_session(term_cli, tmp_path, cols=80, ps1=ps1)
        try:
            local_dir = tmp_path / "local"
            local_dir.mkdir(exist_ok=True)

            remote = tmp_path / "dl_erase.txt"
            remote.write_text("download erase test\n")

            markers = self._fill_screen(term_cli, session)

            local_dest = local_dir / "dl_erase_local.txt"
            term_cli(
                "download", "-s", session,
                str(remote), str(local_dest), "-t", "5",
                check=True,
            )
            self._verify_markers(term_cli, session, markers,
                                 "download 80-col 42-char prompt")
            _assert_clean(term_cli, session, "download erase exactness")
        finally:
            cleanup_session(tmux_socket, session, term_cli)


# ---------------------------------------------------------------------------
# Error path: upload to directory-as-file (CI-safe TC_NOWRITE)
# ---------------------------------------------------------------------------

class TestUploadToDirectory:
    """Upload to a path that is actually a directory triggers TC_NOWRITE.

    This is a CI-friendly alternative to chmod-based permission tests:
    ``mkdir target`` then ``upload file target`` causes the helper to get
    ``IsADirectoryError`` on the trial write, producing TC_NOWRITE.
    """

    def test_upload_to_directory_returns_error(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Uploading to a directory path fails with exit 2."""
        local_dir = tmp_path / "local"
        local_dir.mkdir(exist_ok=True)
        local = local_dir / "dir_target.txt"
        local.write_text("should fail\n")

        # Create a directory with the target filename
        (tmp_path / "dir_target.txt").mkdir()

        result = term_cli(
            "upload", "-s", transfer_session,
            str(local), "dir_target.txt",
            "-t", "5",
            timeout=15.0,
        )
        assert result.returncode == 2, (
            f"Expected exit 2, got {result.returncode}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "cannot write" in result.stderr.lower() or "directory" in result.stderr.lower(), (
            f"Expected write/directory error in stderr: {result.stderr!r}"
        )

    def test_upload_to_directory_leaves_clean_terminal(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """TC_NOWRITE via directory-as-file leaves terminal clean and usable."""
        local_dir = tmp_path / "local"
        local_dir.mkdir(exist_ok=True)
        local = local_dir / "dir_target2.txt"
        local.write_text("should fail\n")

        (tmp_path / "dir_target2.txt").mkdir()

        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )
        term_cli(
            "upload", "-s", transfer_session,
            str(local), "dir_target2.txt",
            "-t", "5",
            timeout=15.0,
        )
        _assert_clean(term_cli, transfer_session,
                      "after upload-to-directory TC_NOWRITE",
                      prompts_before=prompts)


# ---------------------------------------------------------------------------
# Minimum terminal width enforcement
# ---------------------------------------------------------------------------

class TestMinimumWidth:
    """Transfers must refuse on terminals narrower than MIN_TRANSFER_COLS."""

    def test_upload_rejects_narrow_terminal(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Upload on a 30-col terminal is rejected with exit 2."""
        name = unique_session_name()
        term_cli("start", "-s", name, "-c", str(tmp_path),
                 "-x", "30", "-y", "24", check=True)
        assert wait_for_prompt(term_cli, name, timeout=10)
        try:
            local = tmp_path / "narrow.txt"
            local.write_text("test\n")
            result = term_cli(
                "upload", "-s", name,
                str(local), "narrow.txt", "-t", "5",
            )
            assert result.returncode == 2, (
                f"Expected exit 2, got {result.returncode}: {result.stderr}"
            )
            assert "too narrow" in result.stderr.lower()
        finally:
            cleanup_session(tmux_socket, name, term_cli)

    def test_download_rejects_narrow_terminal(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Download on a 30-col terminal is rejected with exit 2."""
        name = unique_session_name()
        term_cli("start", "-s", name, "-c", str(tmp_path),
                 "-x", "30", "-y", "24", check=True)
        assert wait_for_prompt(term_cli, name, timeout=10)
        try:
            remote = tmp_path / "narrow_dl.txt"
            remote.write_text("test\n")
            result = term_cli(
                "download", "-s", name,
                "narrow_dl.txt", str(tmp_path / "local_dl.txt"), "-t", "5",
            )
            assert result.returncode == 2, (
                f"Expected exit 2, got {result.returncode}: {result.stderr}"
            )
            assert "too narrow" in result.stderr.lower()
        finally:
            cleanup_session(tmux_socket, name, term_cli)


# ---------------------------------------------------------------------------
# Pipe support tests (stdin upload / stdout download)
# ---------------------------------------------------------------------------

class TestPipeSupport:
    """Tests for upload from stdin (-) and download to stdout (-)."""

    def test_upload_from_stdin(
        self,
        transfer_session: str,
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Upload from stdin: pipe data in, verify file arrives correctly."""
        data = b"Hello from stdin!\nLine two.\n"

        result = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "upload", "-s", transfer_session,
                "-", "stdin_upload.txt",
                "-t", "5",
            ],
            input=data,
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"upload from stdin failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert b"Uploaded" in result.stdout

        remote = tmp_path / "stdin_upload.txt"
        assert remote.exists()
        assert remote.read_bytes() == data

    def test_upload_from_stdin_binary(
        self,
        transfer_session: str,
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Upload binary data from stdin and verify hash matches."""
        data = bytes(range(256)) * 20  # 5KB of binary data

        result = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "upload", "-s", transfer_session,
                "-", "stdin_binary.bin",
                "-t", "5",
            ],
            input=data,
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"upload from stdin failed: stderr={result.stderr!r}"
        )

        remote = tmp_path / "stdin_binary.bin"
        assert remote.exists()
        assert hashlib.sha256(remote.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_download_to_stdout(
        self,
        transfer_session: str,
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Download to stdout: verify binary data on stdout, status on stderr."""
        content = b"Downloaded to stdout!\nSecond line.\n"
        remote = tmp_path / "dl_stdout.txt"
        remote.write_bytes(content)

        result = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "download", "-s", transfer_session,
                "dl_stdout.txt", "-",
                "-t", "5",
            ],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"download to stdout failed: stderr={result.stderr!r}"
        )
        # Binary data should be on stdout
        assert result.stdout == content
        # Status message should be on stderr (not mixed into stdout)
        assert b"Downloaded" in result.stderr
        assert b"stdout" in result.stderr

    def test_download_to_stdout_binary(
        self,
        transfer_session: str,
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Download binary data to stdout and verify integrity."""
        data = bytes(range(256)) * 20
        remote = tmp_path / "dl_stdout_bin.bin"
        remote.write_bytes(data)

        result = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "download", "-s", transfer_session,
                "dl_stdout_bin.bin", "-",
                "-t", "5",
            ],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"download to stdout failed: stderr={result.stderr!r}"
        )
        assert hashlib.sha256(result.stdout).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_upload_stdin_requires_remote_path(
        self,
        transfer_session: str,
        tmux_socket: str,
    ) -> None:
        """Omitting REMOTE_PATH when uploading from stdin gives exit 2."""
        result = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "upload", "-s", transfer_session,
                "-",
                "-t", "5",
            ],
            input=b"some data",
            capture_output=True,
        )
        assert result.returncode == 2, (
            f"Expected exit 2, got {result.returncode}: stderr={result.stderr!r}"
        )
        assert b"required" in result.stderr.lower()

    def test_upload_stdin_empty(
        self,
        transfer_session: str,
        tmux_socket: str,
    ) -> None:
        """Piping empty data to upload from stdin gives exit 2."""
        result = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "upload", "-s", transfer_session,
                "-", "empty_stdin.txt",
                "-t", "5",
            ],
            input=b"",
            capture_output=True,
        )
        assert result.returncode == 2, (
            f"Expected exit 2, got {result.returncode}: stderr={result.stderr!r}"
        )
        assert b"empty" in result.stderr.lower()

    def test_roundtrip_pipe(
        self,
        transfer_session: str,
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Upload from stdin, download to stdout, verify round-trip integrity."""
        data = os.urandom(10 * 1024)  # 10KB random binary

        # Upload from stdin
        up = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "upload", "-s", transfer_session,
                "-", "roundtrip_pipe.bin",
                "-t", "5",
            ],
            input=data,
            capture_output=True,
        )
        assert up.returncode == 0, (
            f"upload failed: stderr={up.stderr!r}"
        )

        # Download to stdout
        dl = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "download", "-s", transfer_session,
                "roundtrip_pipe.bin", "-",
                "-t", "5",
            ],
            capture_output=True,
        )
        assert dl.returncode == 0, (
            f"download failed: stderr={dl.stderr!r}"
        )
        assert hashlib.sha256(dl.stdout).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_upload_stdin_tty_rejected(
        self,
        transfer_session: str,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Upload from stdin is rejected when stdin is a TTY.

        Uses nested invocation: run term-cli upload inside a term-cli session,
        which gives it a real TTY on stdin (no piped data).
        """
        helper = unique_session_name()
        term_cli("start", "-s", helper, "-x", "80", "-y", "24",
                 "-c", str(tmp_path), check=True)
        assert wait_for_prompt(term_cli, helper, timeout=10)
        try:
            # Run term-cli upload with '-' inside the helper session.
            # Since no data is piped, stdin IS the TTY — isatty() returns True.
            cmd = (
                f"{sys.executable} {TERM_CLI}"
                f" -L {tmux_socket}"
                f" upload -s {transfer_session}"
                f" - tty_test.txt -t 5"
                f"; echo EXIT_CODE=$?"
            )
            term_cli("run", "-s", helper, cmd, "-w", "-t", "10", check=True)
            screen = term_cli("capture", "-s", helper, "-n", "20").stdout
            assert "EXIT_CODE=2" in screen, (
                f"Expected exit code 2, screen:\n{screen}"
            )
            assert "refusing" in screen.lower() or "terminal" in screen.lower(), (
                f"Expected TTY rejection message, screen:\n{screen}"
            )
        finally:
            term_cli("kill", "-s", helper, "-f")

    def test_upload_from_stdin_leaves_clean_screen(
        self,
        transfer_session: str,
        tmux_socket: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Terminal is clean after upload from stdin."""
        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )

        data = b"cleanliness test from stdin\n"
        subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "upload", "-s", transfer_session,
                "-", "stdin_clean.txt",
                "-t", "5",
            ],
            input=data,
            capture_output=True,
            check=True,
        )
        _assert_clean(term_cli, transfer_session, "after stdin upload",
                      prompts_before=prompts)

    def test_download_to_stdout_leaves_clean_screen(
        self,
        transfer_session: str,
        tmux_socket: str,
        term_cli: Callable[..., RunResult],
        tmp_path: Path,
    ) -> None:
        """Terminal is clean after download to stdout."""
        remote = tmp_path / "dl_stdout_clean.txt"
        remote.write_text("cleanliness test to stdout\n")

        prompts = _count_prompt_lines(
            term_cli("capture", "-s", transfer_session).stdout
        )

        subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "download", "-s", transfer_session,
                "dl_stdout_clean.txt", "-",
                "-t", "5",
            ],
            capture_output=True,
            check=True,
        )
        _assert_clean(term_cli, transfer_session, "after stdout download",
                      prompts_before=prompts)

    def test_download_to_stdout_verbose_on_stderr(
        self,
        transfer_session: str,
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """With --verbose, progress info goes to stderr, not stdout."""
        data = b"verbose stdout test\n" * 100
        remote = tmp_path / "dl_verbose_stdout.txt"
        remote.write_bytes(data)

        result = subprocess.run(
            [
                sys.executable, str(TERM_CLI),
                "-L", tmux_socket,
                "download", "-s", transfer_session,
                "dl_verbose_stdout.txt", "-",
                "-v", "-t", "5",
            ],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"download failed: stderr={result.stderr!r}"
        )
        # stdout must contain ONLY the file data — no status/verbose text
        assert result.stdout == data
        # stderr must contain verbose output
        assert b"hash verified" in result.stderr.lower()
        assert b"Downloaded" in result.stderr


# ---------------------------------------------------------------------------
# Transfers through nested tmux
# ---------------------------------------------------------------------------

class TestNestedTmux:
    """Test that transfers work through nested tmux (inner tmux attached
    inside an outer term-cli session).

    This is a realistic scenario: an agent SSH's into a host that is itself
    inside tmux, or the agent launches tmux for process management.  We
    force the chunked download strategy because pipe-pane behaviour through
    nested tmux depends on PTY layering and may vary across environments.
    """

    @staticmethod
    def _enter_inner_tmux(
        term_cli: Callable[..., RunResult],
        outer: str,
        inner: str,
    ) -> None:
        """Create and attach to an inner tmux session from *outer*."""
        term_cli(
            "run", "-s", outer, "-w", "-t", "5",
            f"TMUX='' tmux new-session -d -s {inner} -x 100 -y 20",
            check=True,
        )
        term_cli(
            "run", "-s", outer,
            f"TMUX='' tmux attach -t {inner}",
        )
        term_cli("wait-idle", "-s", outer, "-i", "2", "-t", "10", check=True)

    @staticmethod
    def _leave_inner_tmux(
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        outer: str,
        inner: str,
    ) -> None:
        """Detach from inner tmux and clean up both sessions."""
        term_cli("send-key", "-s", outer, "C-b")
        time.sleep(0.1)
        term_cli("send-key", "-s", outer, "d")
        term_cli("wait", "-s", outer, "-t", "5")
        subprocess.run(
            ["tmux", "-L", tmux_socket, "kill-session", "-t",
             f"={inner}:"],
            capture_output=True,
        )
        term_cli("kill", "-s", outer, "-f")

    def test_chunked_download_through_nested_tmux(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Chunked download works when the session is inside nested tmux."""
        name = unique_session_name()
        inner = f"inner-{name}"
        term_cli(
            "start", "-s", name, "-c", str(tmp_path),
            "-x", "120", "-y", "30",
            check=True,
        )
        assert wait_for_prompt(term_cli, name, timeout=10)

        # Force chunked strategy so we exercise the screen-capture path
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t",
             f"={name}:", "@term_cli_dl_strategy", "chunked"],
            capture_output=True, check=True,
        )

        try:
            test_data = "nested download test: chunked path works!\n"
            (tmp_path / "nested_dl.txt").write_text(test_data)

            self._enter_inner_tmux(term_cli, name, inner)

            local_dest = tmp_path / "local" / "nested_dl.txt"
            local_dest.parent.mkdir(exist_ok=True)
            term_cli(
                "download", "-s", name,
                str(tmp_path / "nested_dl.txt"), str(local_dest),
                "-v", "-t", "30",
                check=True,
            )

            assert local_dest.read_text() == test_data
        finally:
            self._leave_inner_tmux(term_cli, tmux_socket, name, inner)

    def test_upload_through_nested_tmux(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Upload works when the session is inside nested tmux."""
        name = unique_session_name()
        inner = f"inner-{name}"
        term_cli(
            "start", "-s", name, "-c", str(tmp_path),
            "-x", "120", "-y", "30",
            check=True,
        )
        assert wait_for_prompt(term_cli, name, timeout=10)

        try:
            local_src = tmp_path / "local" / "nested_up.txt"
            local_src.parent.mkdir(exist_ok=True)
            upload_data = "nested upload test data\n"
            local_src.write_text(upload_data)

            self._enter_inner_tmux(term_cli, name, inner)

            remote_dest = str(tmp_path / "nested_up_remote.txt")
            term_cli(
                "upload", "-s", name,
                str(local_src), remote_dest,
                "-v", "-t", "30",
                check=True,
            )

            assert Path(remote_dest).read_text() == upload_data
        finally:
            self._leave_inner_tmux(term_cli, tmux_socket, name, inner)


# ---------------------------------------------------------------------------
# Python not available
# ---------------------------------------------------------------------------

class TestPythonNotAvailable:
    """Test error handling when Python 3 is not available on the remote."""

    def test_upload_fails_when_python_missing(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Upload returns exit 1 with clear error when python3/python not found."""
        name = unique_session_name()
        term_cli(
            "start", "-s", name, "-c", str(tmp_path),
            check=True,
        )
        assert wait_for_prompt(term_cli, name, timeout=10)
        try:
            # Create shadow directory with dummy python3/python that exit 1
            shadow = tmp_path / "shadow"
            shadow.mkdir()
            for bin_name in ("python3", "python"):
                script = shadow / bin_name
                script.write_text("#!/bin/sh\nexit 1\n")
                script.chmod(0o755)

            # Prepend shadow dir to PATH so dummies are found first
            term_cli(
                "run", "-s", name, "-w", "-t", "5",
                f"export PATH={shadow}:$PATH",
                check=True,
            )

            local = tmp_path / "nopy.txt"
            local.write_text("test content\n")
            result = term_cli(
                "upload", "-s", name,
                str(local), "nopy.txt",
                "-t", "15",
            )

            assert result.returncode == 1
            assert "python" in result.stderr.lower()

            # Restore PATH so cleanup commands work
            term_cli(
                "run", "-s", name, "-w", "-t", "5",
                f"export PATH=$(echo $PATH | sed 's|{shadow}:||')",
                check=True,
            )

            # Terminal should be usable after failure
            _assert_clean(term_cli, name, "after python-missing upload")

        finally:
            cleanup_session(tmux_socket, name, term_cli)

    def test_download_fails_when_python_missing(
        self,
        term_cli: Callable[..., RunResult],
        tmux_socket: str,
        tmp_path: Path,
    ) -> None:
        """Download returns exit 1 when python3/python not found."""
        name = unique_session_name()
        term_cli(
            "start", "-s", name, "-c", str(tmp_path),
            check=True,
        )
        assert wait_for_prompt(term_cli, name, timeout=10)
        try:
            shadow = tmp_path / "shadow"
            shadow.mkdir()
            for bin_name in ("python3", "python"):
                script = shadow / bin_name
                script.write_text("#!/bin/sh\nexit 1\n")
                script.chmod(0o755)

            term_cli(
                "run", "-s", name, "-w", "-t", "5",
                f"export PATH={shadow}:$PATH",
                check=True,
            )

            # Create a file to attempt downloading
            remote = tmp_path / "exists.txt"
            remote.write_text("won't download\n")

            result = term_cli(
                "download", "-s", name,
                str(remote), str(tmp_path / "local_exists.txt"),
                "-t", "15",
            )

            assert result.returncode == 1
            assert "python" in result.stderr.lower()

            # Restore PATH
            term_cli(
                "run", "-s", name, "-w", "-t", "5",
                f"export PATH=$(echo $PATH | sed 's|{shadow}:||')",
                check=True,
            )

            _assert_clean(term_cli, name, "after python-missing download")

        finally:
            cleanup_session(tmux_socket, name, term_cli)


# ---------------------------------------------------------------------------
# Probe parsing robustness (unit)
# ---------------------------------------------------------------------------

class TestProbeParsingRobustness:
    """Unit tests for transfer probe marker parsing under wrapped/truncated output."""

    @pytest.fixture(scope="class")
    def transfer_module(self) -> Any:
        """Import term-cli as a Python module for direct function tests."""
        from importlib.machinery import SourceFileLoader

        loader = SourceFileLoader("term_cli_transfer_module", str(TERM_CLI))
        return loader.load_module()

    def test_probe_python_parses_tag_with_prefix_noise(
        self,
        transfer_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_probe_python should detect TC_PY3 even when not at line start."""
        fixed_pid = 4242
        fixed_time = 1234.567
        probe_id = f"{fixed_pid}_{int(fixed_time * 1000) & 0xFFFFFF}"

        monkeypatch.setattr(transfer_module.os, "getpid", lambda: fixed_pid)
        monkeypatch.setattr(transfer_module.time, "time", lambda: fixed_time)

        # First marker is clipped at line end; second marker is intact but
        # prefixed by prompt/noise text.
        screen = (
            f"TC_PY3_{probe_id}_O\n"
            f"very/long/path$ TC_PY3_{probe_id}_OK\n"
            f"TC_PY_DONE_{probe_id}\n"
        )
        monkeypatch.setattr(
            transfer_module,
            "_remote_exec_until_marker",
            lambda *_args, **_kwargs: screen,
        )

        py_bin = transfer_module._probe_python("dummy", 5.0)
        assert py_bin == "python3"

    def test_probe_python_parses_python_alias_major3(
        self,
        transfer_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_probe_python should accept python when marker reports major=3."""
        fixed_pid = 777
        fixed_time = 2000.0
        probe_id = f"{fixed_pid}_{int(fixed_time * 1000) & 0xFFFFFF}"

        monkeypatch.setattr(transfer_module.os, "getpid", lambda: fixed_pid)
        monkeypatch.setattr(transfer_module.time, "time", lambda: fixed_time)
        monkeypatch.setattr(
            transfer_module,
            "_remote_exec_until_marker",
            lambda *_args, **_kwargs: f"tmux$ TC_PYBIN_{probe_id}_3\n",
        )

        py_bin = transfer_module._probe_python("dummy", 5.0)
        assert py_bin == "python"

    def test_probe_python_missing_raises_error(
        self,
        transfer_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_probe_python raises when neither python3 nor python=3 is detected."""
        monkeypatch.setattr(
            transfer_module,
            "_remote_exec_until_marker",
            lambda *_args, **_kwargs: "no probe markers here\n",
        )

        with pytest.raises(RuntimeError, match="Python 3 is not available"):
            transfer_module._probe_python("dummy", 5.0)

    def test_remote_file_exists_parses_yes_no_with_partial_first_tag(
        self,
        transfer_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_remote_file_exists should tolerate a partially clipped first marker."""
        fixed_pid = 9090
        fixed_time = 3456.789
        marker = f"{fixed_pid}_{int(fixed_time * 1000) & 0xFFFFFF}"
        yes_tag = f"TC_FE_{marker}_0"
        no_tag = f"TC_FE_{marker}_1"

        monkeypatch.setattr(transfer_module.os, "getpid", lambda: fixed_pid)
        monkeypatch.setattr(transfer_module.time, "time", lambda: fixed_time)

        monkeypatch.setattr(
            transfer_module,
            "_remote_exec_until_marker",
            lambda *_args, **_kwargs: f"{yes_tag[:-1]}\nlong/prompt$ {yes_tag}\n",
        )
        assert transfer_module._remote_file_exists("dummy", "x.txt", 5.0) is True

        monkeypatch.setattr(
            transfer_module,
            "_remote_exec_until_marker",
            lambda *_args, **_kwargs: f"{no_tag[:-1]}\nlong/prompt$ {no_tag}\n",
        )
        assert transfer_module._remote_file_exists("dummy", "x.txt", 5.0) is False

    def test_cmd_download_falls_back_to_chunked_on_pipe_hash_mismatch(
        self,
        transfer_module: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """cmd_download should retry with chunked when pipe-pane hash mismatches."""
        out_path = tmp_path / "fallback_chunked.bin"
        chunked_data = b"chunked-data-ok"
        chunked_sha = hashlib.sha256(chunked_data).hexdigest()

        monkeypatch.setattr(transfer_module, "_require_session", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_require_unlocked", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_require_prompt_ready", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_is_alternate_screen", lambda *_: False)
        monkeypatch.setattr(transfer_module, "_get_pane_dimensions", lambda *_: (80, 24))
        monkeypatch.setattr(transfer_module, "_hide_probe_start", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_probe_python", lambda *_: "python3")
        monkeypatch.setattr(transfer_module, "_remote_file_exists", lambda *_: True)
        monkeypatch.setattr(transfer_module, "_restore_terminal", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_get_dl_strategy", lambda *_: None)

        set_calls: list[str] = []
        monkeypatch.setattr(
            transfer_module,
            "_set_dl_strategy",
            lambda _session, value: set_calls.append(value),
        )

        calls = {"pipe": 0, "chunked": 0}

        def fake_download_pipe(*_args: Any, **_kwargs: Any) -> tuple[bytes, str]:
            calls["pipe"] += 1
            return (b"pipe-data", "f" * 64)

        def fake_download_chunked(*_args: Any, **_kwargs: Any) -> tuple[bytes, str]:
            calls["chunked"] += 1
            return (chunked_data, chunked_sha)

        monkeypatch.setattr(transfer_module, "_download_pipe", fake_download_pipe)
        monkeypatch.setattr(transfer_module, "_download_chunked", fake_download_chunked)

        args = argparse.Namespace(
            session="dummy",
            remote_path="remote.txt",
            local_path=str(out_path),
            timeout=5.0,
            verbose=False,
            force=False,
        )
        transfer_module.cmd_download(args)

        assert calls == {"pipe": 1, "chunked": 1}
        assert set_calls == ["chunked"]
        assert out_path.read_bytes() == chunked_data

    def test_cmd_download_uses_chunked_in_alternate_screen(
        self,
        transfer_module: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """cmd_download skips pipe strategy when starting on alternate screen."""
        out_path = tmp_path / "alt_start_chunked.bin"
        chunked_data = b"chunked-alt-ok"
        chunked_sha = hashlib.sha256(chunked_data).hexdigest()

        monkeypatch.setattr(transfer_module, "_require_session", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_require_unlocked", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_require_prompt_ready", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_is_alternate_screen", lambda *_: True)
        monkeypatch.setattr(transfer_module, "_get_pane_dimensions", lambda *_: (80, 24))
        monkeypatch.setattr(transfer_module, "_hide_probe_start", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_probe_python", lambda *_: "python3")
        monkeypatch.setattr(transfer_module, "_remote_file_exists", lambda *_: True)
        monkeypatch.setattr(transfer_module, "_restore_terminal", lambda *_: None)
        monkeypatch.setattr(transfer_module, "_get_dl_strategy", lambda *_: None)

        set_calls: list[str] = []
        monkeypatch.setattr(
            transfer_module,
            "_set_dl_strategy",
            lambda _session, value: set_calls.append(value),
        )

        calls = {"pipe": 0, "chunked": 0}

        def fake_download_pipe(*_args: Any, **_kwargs: Any) -> tuple[bytes, str]:
            calls["pipe"] += 1
            return (b"pipe-data", "f" * 64)

        def fake_download_chunked(*_args: Any, **_kwargs: Any) -> tuple[bytes, str]:
            calls["chunked"] += 1
            return (chunked_data, chunked_sha)

        monkeypatch.setattr(transfer_module, "_download_pipe", fake_download_pipe)
        monkeypatch.setattr(transfer_module, "_download_chunked", fake_download_chunked)

        args = argparse.Namespace(
            session="dummy",
            remote_path="remote.txt",
            local_path=str(out_path),
            timeout=5.0,
            verbose=False,
            force=False,
        )
        transfer_module.cmd_download(args)

        assert calls == {"pipe": 0, "chunked": 1}
        assert set_calls == []
        assert out_path.read_bytes() == chunked_data

    def test_download_chunked_rejects_unparseable_info_marker(
        self,
        transfer_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_download_chunked should error when TC_DL_INFO cannot be parsed."""
        monkeypatch.setattr(transfer_module, "_get_pane_dimensions", lambda *_: (80, 24))
        monkeypatch.setattr(transfer_module, "_run_helper", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            transfer_module,
            "_wait_for_any_text",
            lambda *_args, **_kwargs: ("TC_DL_INFO", 0.0),
        )
        monkeypatch.setattr(
            transfer_module,
            "_capture_screen",
            lambda *_args, **_kwargs: "noise without info marker",
        )

        with pytest.raises(RuntimeError, match="could not parse TC_DL_INFO"):
            transfer_module._download_chunked(
                "dummy",
                "remote.txt",
                "python3",
                5.0,
                False,
                already_on_alt=False,
            )
