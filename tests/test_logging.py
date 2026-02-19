"""
Tests for logging commands: pipe-log, unpipe.
"""

from __future__ import annotations

from pathlib import Path

from conftest import wait_for_file_content


class TestPipeLog:
    """Tests for the 'pipe-log' command."""

    def test_pipe_log_creates_file(self, session, term_cli, tmp_path):
        """pipe-log starts logging to file."""
        logfile = tmp_path / "test.log"
        result = term_cli("pipe-log", "-s", session, str(logfile))
        assert result.ok
        assert "Piping output to" in result.stdout
        assert str(logfile) in result.stdout

    def test_pipe_log_captures_output(self, session, term_cli, tmp_path):
        """pipe-log captures command output."""
        logfile = tmp_path / "test.log"
        term_cli("pipe-log", "-s", session, str(logfile))
        term_cli("run", "-s", session, "echo logged_content", "-w")
        assert wait_for_file_content(logfile, "logged_content"), "Content not found in log file"
        term_cli("unpipe", "-s", session)
        
        content = logfile.read_text()
        assert "logged_content" in content

    def test_pipe_log_strips_ansi(self, session, term_cli, tmp_path):
        """pipe-log strips ANSI escape codes by default."""
        logfile = tmp_path / "test.log"
        term_cli("pipe-log", "-s", session, str(logfile))
        # Send colored output - use \x1b which is the actual escape byte
        term_cli("run", "-s", session, "printf '\\033[31mcolored_text\\033[0m'", "-w")
        assert wait_for_file_content(logfile, "colored_text"), "Content not found in log file"
        term_cli("unpipe", "-s", session)
        
        content = logfile.read_text()
        # Should have the text but NOT the escape codes
        assert "colored_text" in content
        # Check that actual escape bytes are stripped (not the literal string \\033)
        assert "\x1b" not in content, f"ANSI escape codes not stripped: {repr(content)}"

    def test_pipe_log_raw_preserves_ansi(self, session, term_cli, tmp_path):
        """pipe-log --raw preserves ANSI escape codes."""
        logfile = tmp_path / "test.log"
        result = term_cli("pipe-log", "-s", session, str(logfile), "-r")
        assert result.ok
        term_cli("run", "-s", session, "printf '\\033[31mraw_text\\033[0m'", "-w")
        assert wait_for_file_content(logfile, "raw_text"), "Content not found in log file"
        term_cli("unpipe", "-s", session)
        
        content = logfile.read_text()
        # Should have the text AND the escape codes (raw mode)
        assert "raw_text" in content
        assert "\x1b" in content, f"ANSI escape codes were stripped in raw mode: {repr(content)}"

    def test_pipe_log_appends(self, session, term_cli, tmp_path):
        """pipe-log appends to existing file."""
        logfile = tmp_path / "test.log"
        logfile.write_text("existing\n")
        
        term_cli("pipe-log", "-s", session, str(logfile))
        term_cli("run", "-s", session, "echo appended", "-w")
        assert wait_for_file_content(logfile, "appended"), "Content not found in log file"
        term_cli("unpipe", "-s", session)
        
        content = logfile.read_text()
        assert "existing" in content
        assert "appended" in content

    def test_pipe_log_reports_mode(self, session, term_cli, tmp_path):
        """pipe-log reports clean vs raw mode."""
        logfile = tmp_path / "test.log"
        
        result = term_cli("pipe-log", "-s", session, str(logfile))
        assert "(clean)" in result.stdout
        term_cli("unpipe", "-s", session)
        
        result = term_cli("pipe-log", "-s", session, str(logfile), "-r")
        assert "(raw)" in result.stdout

    def test_pipe_log_nonexistent_session(self, term_cli, tmp_path):
        """pipe-log on non-existent session raises error."""
        logfile = tmp_path / "test.log"
        result = term_cli("pipe-log", "-s", "nonexistent_xyz", str(logfile))
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_pipe_log_multiple_commands(self, session, term_cli, tmp_path):
        """pipe-log captures multiple commands."""
        logfile = tmp_path / "test.log"
        term_cli("pipe-log", "-s", session, str(logfile))
        
        term_cli("run", "-s", session, "echo first", "-w")
        term_cli("run", "-s", session, "echo second", "-w")
        term_cli("run", "-s", session, "echo third", "-w")
        assert wait_for_file_content(logfile, "third"), "Content not found in log file"
        term_cli("unpipe", "-s", session)
        
        content = logfile.read_text()
        assert "first" in content
        assert "second" in content
        assert "third" in content

    def test_pipe_log_creates_parent_dirs(self, session, term_cli, tmp_path):
        """pipe-log works with nested directory paths."""
        # Note: pipe-log does NOT create parent directories automatically.
        # It relies on the parent directory existing. This test verifies
        # that pipe-log works when the full path exists.
        logfile = tmp_path / "subdir" / "nested" / "test.log"
        logfile.parent.mkdir(parents=True, exist_ok=True)
        
        result = term_cli("pipe-log", "-s", session, str(logfile))
        assert result.ok
        
        # Verify logging actually works in nested path
        term_cli("run", "-s", session, "echo nested_test", "-w")
        assert wait_for_file_content(logfile, "nested_test"), "Content not found in log file"
        term_cli("unpipe", "-s", session)
        
        assert logfile.exists()
        assert "nested_test" in logfile.read_text()

    def test_pipe_log_fails_nonexistent_parent_dir(self, session, term_cli, tmp_path):
        """pipe-log fails when parent directory doesn't exist."""
        # Path with non-existent parent directory
        logfile = tmp_path / "nonexistent_parent" / "test.log"
        
        # pipe-log command should fail with validation error
        result = term_cli("pipe-log", "-s", session, str(logfile))
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR
        assert "parent directory" in result.stderr.lower() or "does not exist" in result.stderr.lower()

    def test_pipe_log_second_invocation_requires_unpipe_first(self, session, term_cli, tmp_path):
        """Re-running pipe-log should fail clearly while piping is active."""
        first = tmp_path / "first.log"
        second = tmp_path / "second.log"

        term_cli("pipe-log", "-s", session, str(first), check=True)
        result = term_cli("pipe-log", "-s", session, str(second))
        assert not result.ok
        assert "already piping" in result.stderr.lower()
        term_cli("unpipe", "-s", session, check=True)


class TestUnpipe:
    """Tests for the 'unpipe' command."""

    def test_unpipe_stops_logging(self, session, term_cli, tmp_path):
        """unpipe stops logging to file."""
        logfile = tmp_path / "test.log"
        term_cli("pipe-log", "-s", session, str(logfile))
        term_cli("run", "-s", session, "echo before_unpipe_marker", "-w")
        assert wait_for_file_content(logfile, "before_unpipe_marker"), "Content not found in log file"
        
        result = term_cli("unpipe", "-s", session)
        assert result.ok
        assert "Stopped piping" in result.stdout
        
        # Get size before additional command
        size_after_unpipe = logfile.stat().st_size
        
        # Commands after unpipe should not be logged
        term_cli("run", "-s", session, "echo AFTER_UNPIPE_UNIQUE_MARKER", "-w")
        
        content = logfile.read_text()
        assert "before_unpipe_marker" in content
        # The unique marker should NOT appear in the log
        assert "AFTER_UNPIPE_UNIQUE_MARKER" not in content, \
            f"Commands after unpipe were logged: {content}"

    def test_unpipe_idempotent(self, session, term_cli):
        """unpipe when not piping doesn't error."""
        # Should not fail even if nothing is being piped
        result = term_cli("unpipe", "-s", session)
        assert result.ok

    def test_unpipe_nonexistent_session(self, term_cli):
        """unpipe on non-existent session raises error."""
        result = term_cli("unpipe", "-s", "nonexistent_xyz")
        assert not result.ok
        assert "does not exist" in result.stderr
