"""
Tests for term-assist: human companion tool for session sharing.

Note: We can't easily test actual attach behavior since it uses os.execvp(),
but we can test command parsing, session resolution, and integration with
term-cli's request system.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from conftest import RunResult, cleanup_session, unique_session_name


# Path to term-assist
TERM_ASSIST = Path(__file__).parent.parent / "term-assist"


def _run_term_assist(*args: str, socket: str | None = None) -> RunResult:
    """Run term-assist with the given arguments."""
    full_args = list(args)
    if socket:
        # Insert socket option at the beginning
        full_args = ["-L", socket] + full_args
    proc = subprocess.run(
        [sys.executable, str(TERM_ASSIST), *full_args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return RunResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


class TestHelp:
    """Tests for help output."""

    def test_help_shows_commands(self):
        """Main help shows all commands."""
        result = _run_term_assist("--help")
        assert result.ok
        assert "list" in result.stdout
        assert "attach" in result.stdout
        assert "done" in result.stdout
        assert "detach" in result.stdout
        assert "start" in result.stdout
        assert "kill" in result.stdout
        # join should NOT be present (merged into attach)
        assert "join" not in result.stdout

    def test_help_shows_keybindings(self):
        """Help shows keybindings for attached sessions."""
        result = _run_term_assist("--help")
        assert result.ok
        assert "Ctrl+B Enter" in result.stdout
        assert "Ctrl+B d" in result.stdout

    def test_attach_help(self):
        """Attach help shows options."""
        result = _run_term_assist("attach", "--help")
        assert result.ok
        assert "--session" in result.stdout or "-s" in result.stdout
        assert "--readonly" in result.stdout or "-r" in result.stdout

    def test_list_help(self):
        """List help shows --all option."""
        result = _run_term_assist("list", "--help")
        assert result.ok
        assert "--all" in result.stdout or "-a" in result.stdout


class TestCommandAbbreviation:
    """Tests for command abbreviation."""

    def test_abbreviation_l_is_ambiguous(self, term_assist):
        """'l' is ambiguous (list, lock)."""
        result = term_assist("l")
        # Should fail with ambiguous error
        assert not result.ok
        assert "ambiguous" in result.stderr.lower()

    def test_abbreviation_li_for_list(self, term_assist):
        """'li' abbreviates to 'list'."""
        result = term_assist("li")
        # Should work (might say "No sessions" but shouldn't error on command parsing)
        assert result.ok or "No sessions" in result.stdout

    def test_abbreviation_lo_for_lock(self, session, term_cli, term_assist):
        """'lo' abbreviates to 'lock'."""
        result = term_assist("lo", "-s", session)
        # Should work and lock the session
        assert result.ok
        assert "locked" in result.stdout.lower()

    def test_abbreviation_a_for_attach(self, session, term_cli, term_assist):
        """'a' abbreviates to 'attach'."""
        # Use explicit session to avoid "no sessions" error in clean test environments
        result = term_assist("a", "-s", session)
        # Will fail because we're not in a terminal (execvp fails), but should parse command
        # The key is it shouldn't say "unknown command" or "ambiguous"
        assert "ambiguous" not in result.stderr.lower()
        assert "unknown" not in result.stderr.lower()

    def test_abbreviation_do_for_done(self):
        """'do' abbreviates to 'done'."""
        result = _run_term_assist("do")
        # Will fail because not in tmux, but should parse the command
        assert not result.ok
        assert "tmux" in result.stderr.lower() or "session" in result.stderr.lower()

    def test_abbreviation_det_for_detach(self):
        """'det' abbreviates to 'detach'."""
        result = _run_term_assist("det")
        # Will fail because not in tmux
        assert not result.ok
        assert "tmux" in result.stderr.lower()

    def test_abbreviation_st_for_start(self):
        """'st' abbreviates to 'start'.
        
        This test uses its own isolated tmux socket to avoid flakiness from
        parallel test interference with session creation.
        """
        import subprocess
        import sys
        
        socket = f"pytest_st_abbrev_{unique_session_name()}"
        session = unique_session_name()
        term_assist_path = Path(__file__).parent.parent / "term-assist"
        term_cli_path = Path(__file__).parent.parent / "term-cli"
        
        try:
            # Run term-assist start with abbreviated command
            result = subprocess.run(
                [sys.executable, str(term_assist_path), "-L", socket, "st", "-s", session],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Should succeed in creating the session
            assert result.returncode == 0, f"Expected success, got: {result.stderr}"
            # Verify command was recognized (not ambiguous)
            assert "ambiguous" not in result.stderr.lower()
        finally:
            # Cleanup: kill the entire tmux server for this socket
            subprocess.run(
                ["tmux", "-L", socket, "kill-server"],
                capture_output=True,
            )

    def test_ambiguous_abbreviation_error(self):
        """Ambiguous abbreviation gives helpful error."""
        # 'd' could be 'done', 'detach', etc.
        result = _run_term_assist("d")
        assert not result.ok
        assert "ambiguous" in result.stderr.lower() or "could be" in result.stderr.lower()


class TestList:
    """Tests for the 'list' command."""

    def test_list_shows_pending_requests(self, session, term_cli, term_assist):
        """List shows sessions with pending requests."""
        # Create a request
        term_cli("request", "-s", session, "-m", "Test request message")
        
        result = term_assist("list")
        assert result.ok
        assert session in result.stdout
        assert "Test request message" in result.stdout

    def test_list_all_shows_sessions_without_requests(self, session, term_cli, term_assist):
        """List --all shows sessions even without requests."""
        # Session exists but has no request
        result = term_assist("list", "-a")
        assert result.ok
        assert session in result.stdout
        assert "no request" in result.stdout.lower()

    def test_list_handles_no_pending_gracefully(self, session, term_cli, term_assist):
        """List without pending requests shows appropriate message."""
        # Session exists but has no request - list (without -a) should work
        result = term_assist("list")
        assert result.ok
        # Should either show "No pending requests" or just be empty of this session
        # (other parallel tests might have sessions with requests)


class TestDone:
    """Tests for the 'done' command."""

    def test_done_requires_session_outside_tmux(self):
        """Done without -s outside tmux fails."""
        result = _run_term_assist("done")
        assert not result.ok
        assert "tmux" in result.stderr.lower() or "session" in result.stderr.lower()

    def test_done_with_session_no_request(self, session, term_cli, term_assist):
        """Done on session without pending request is a no-op."""
        # No request made, done should succeed silently (idempotent)
        result = term_assist("done", "-s", session)
        assert result.ok

    def test_done_clears_request(self, session, term_cli, term_assist):
        """Done clears a pending request."""
        # Create a request
        term_cli("request", "-s", session, "-m", "Need help")
        
        # Verify it's pending
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 0  # pending
        
        # Mark done via term-assist
        result = term_assist("done", "-s", session)
        assert result.ok
        
        # Verify it's cleared
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 1  # not pending

    def test_done_nonexistent_session(self, term_assist):
        """Done on nonexistent session fails."""
        result = term_assist("done", "-s", "nonexistent_session_xyz_123")
        assert not result.ok
        assert "does not exist" in result.stderr.lower() or "not found" in result.stderr.lower()


class TestStart:
    """Tests for the 'start' command."""

    def test_start_creates_session(self, term_cli, term_assist):
        """Start creates a new session."""
        session = unique_session_name()
        try:
            result = term_assist("start", "-s", session)
            assert result.ok
            assert session in result.stdout
            
            # Verify session exists via term-cli
            status = term_cli("status", "-s", session)
            assert status.ok
        finally:
            # Cleanup
            term_cli("kill", "-s", session, "-f")

    def test_start_with_dimensions(self, term_cli, term_assist):
        """Start with custom dimensions."""
        session = unique_session_name()
        try:
            result = term_assist("start", "-s", session, "-x", "100", "-y", "30")
            assert result.ok
            assert "100x30" in result.stdout
        finally:
            term_cli("kill", "-s", session, "-f")

    def test_start_with_cwd(self, term_cli, term_assist, tmp_path):
        """Start with working directory."""
        session = unique_session_name()
        try:
            result = term_assist("start", "-s", session, "-c", str(tmp_path))
            assert result.ok
            
            # Verify cwd
            term_cli("run", "-s", session, "pwd", "-w")
            capture = term_cli("capture", "-s", session)
            assert str(tmp_path) in capture.stdout
        finally:
            term_cli("kill", "-s", session, "-f")

    def test_start_existing_session_fails(self, session, term_cli, term_assist):
        """Start fails if session already exists."""
        result = term_assist("start", "-s", session)
        assert not result.ok
        assert "already exists" in result.stderr.lower()

    def test_start_invalid_cwd_fails(self, term_assist):
        """Start with nonexistent cwd fails."""
        session = unique_session_name()
        result = term_assist("start", "-s", session, "-c", "/nonexistent/path/xyz")
        assert not result.ok
        assert "does not exist" in result.stderr.lower()


class TestAttachSessionResolution:
    """Tests for attach command's session resolution logic.
    
    Note: We can't test actual attach (uses execvp), but we can test
    the error messages which reveal the resolution logic.
    """

    def test_attach_explicit_session_not_found(self, term_assist):
        """Attach to nonexistent session gives error."""
        result = term_assist("attach", "-s", "nonexistent_session_xyz_123")
        assert not result.ok
        assert "does not exist" in result.stderr.lower()

    def test_attach_prefers_session_with_request(self, term_cli, term_assist, tmux_socket):
        """Attach without -s prefers session with pending request."""
        session1 = unique_session_name()
        session2 = unique_session_name()
        
        try:
            # Create two sessions
            term_cli("start", "-s", session1)
            term_cli("start", "-s", session2)
            
            # Add request to session2 only
            term_cli("request", "-s", session2, "-m", "Help needed")
            
            # Try to attach without -s
            # It will fail at execvp, but the stderr should show which session it picked
            result = term_assist("attach")
            # The message should mention session2 (has request)
            # Note: In parallel tests, other sessions with requests might exist,
            # so we just check it picked ONE session with a pending request
            assert "pending request" in result.stderr.lower()
        finally:
            cleanup_session(tmux_socket, session1, term_cli)
            cleanup_session(tmux_socket, session2, term_cli)

    def test_attach_with_explicit_session(self, session, term_cli, term_assist):
        """Attach with explicit -s uses that session."""
        # Try to attach with explicit session name
        # It will fail at execvp (not a terminal), but we can verify it tried
        result = term_assist("attach", "-s", session)
        # Should fail because we're not in a terminal
        assert not result.ok
        # But shouldn't complain about session not existing
        assert "does not exist" not in result.stderr.lower()


class TestIntegrationWithTermCli:
    """Integration tests between term-assist and term-cli."""

    def test_request_list_done_workflow(self, session, term_cli, term_assist):
        """Full workflow: request -> list -> done -> verify cleared."""
        # Agent requests help
        req = term_cli("request", "-s", session, "-m", "Please enter password")
        assert req.ok
        
        # Human sees the request
        list_result = term_assist("list")
        assert list_result.ok
        assert session in list_result.stdout
        assert "Please enter password" in list_result.stdout
        
        # Human marks it done (without actually attaching)
        done_result = term_assist("done", "-s", session)
        assert done_result.ok
        
        # Agent's request-wait would now return (but we can verify via status)
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 1  # not pending

    def test_multiple_requests_listed(self, term_cli, term_assist):
        """Multiple sessions with requests are all listed."""
        session1 = unique_session_name()
        session2 = unique_session_name()
        
        try:
            term_cli("start", "-s", session1)
            term_cli("start", "-s", session2)
            
            term_cli("request", "-s", session1, "-m", "Help with session 1")
            term_cli("request", "-s", session2, "-m", "Help with session 2")
            
            list_result = term_assist("list")
            assert list_result.ok
            assert session1 in list_result.stdout
            assert session2 in list_result.stdout
            assert "Help with session 1" in list_result.stdout
            assert "Help with session 2" in list_result.stdout
        finally:
            term_cli("kill", "-s", session1, "-f")
            term_cli("kill", "-s", session2, "-f")


class TestExitCodes:
    """Tests for exit codes."""

    def test_success_exit_code(self, term_assist):
        """Successful commands return 0."""
        result = term_assist("list")
        assert result.returncode == 0

    def test_input_error_exit_code(self, term_assist):
        """Invalid input returns exit code 2."""
        result = term_assist("attach", "-s", "nonexistent_xyz_123")
        assert result.returncode == 2  # ValueError -> exit 2

    def test_runtime_error_exit_code(self, session, term_cli, term_assist):
        """Runtime errors return exit code 1."""
        # Try to start a session that already exists
        result = term_assist("start", "-s", session)
        assert result.returncode == 1  # RuntimeError -> exit 1


class TestKill:
    """Tests for the 'kill' command."""

    def test_kill_requires_session_or_all(self, term_assist):
        """Kill without --session or --all fails."""
        result = term_assist("kill")
        assert not result.ok
        assert "session" in result.stderr.lower() or "all" in result.stderr.lower()

    def test_kill_cannot_use_both_session_and_all(self, term_assist):
        """Kill with both --session and --all fails."""
        result = term_assist("kill", "-s", "test", "-a")
        assert not result.ok
        assert "cannot" in result.stderr.lower()

    def test_kill_session(self, term_cli, term_assist):
        """Kill destroys a specific session."""
        session = unique_session_name()
        try:
            # Create session
            term_cli("start", "-s", session)
            
            # Verify it exists
            status = term_cli("status", "-s", session)
            assert status.ok
            
            # Kill via term-assist
            result = term_assist("kill", "-s", session)
            assert result.ok
            assert session in result.stdout
            
            # Verify it's gone
            status = term_cli("status", "-s", session)
            assert not status.ok
        finally:
            # Cleanup in case test fails
            term_cli("kill", "-s", session, "-f")

    def test_kill_nonexistent_session_fails(self, term_assist):
        """Kill on nonexistent session fails."""
        result = term_assist("kill", "-s", "nonexistent_session_xyz_123")
        assert not result.ok
        assert "does not exist" in result.stderr.lower()

    def test_kill_all_sessions(self, term_cli, term_assist, tmux_socket):
        """Kill --all destroys all sessions."""
        session1 = unique_session_name()
        session2 = unique_session_name()
        
        try:
            # Create two sessions
            term_cli("start", "-s", session1)
            term_cli("start", "-s", session2)
            
            # Verify they exist
            assert term_cli("status", "-s", session1).ok
            assert term_cli("status", "-s", session2).ok
            
            # Kill all via term-assist
            result = term_assist("kill", "-a")
            assert result.ok
            assert session1 in result.stdout
            assert session2 in result.stdout
            
            # Verify they're gone
            assert not term_cli("status", "-s", session1).ok
            assert not term_cli("status", "-s", session2).ok
        finally:
            # Cleanup in case test fails
            cleanup_session(tmux_socket, session1, term_cli)
            cleanup_session(tmux_socket, session2, term_cli)

    def test_kill_all_no_sessions(self, term_assist):
        """Kill --all with no sessions is handled gracefully."""
        # This test runs in an isolated socket, so there may be no sessions
        # or other tests' sessions. The key is it shouldn't crash.
        result = term_assist("kill", "-a")
        # Either succeeds with "No sessions" or kills existing sessions
        assert result.ok

    def test_kill_abbreviation(self, term_cli, term_assist):
        """'ki' abbreviates to 'kill'."""
        session = unique_session_name()
        try:
            term_cli("start", "-s", session)
            result = term_assist("ki", "-s", session)
            assert result.ok
            assert session in result.stdout
        finally:
            term_cli("kill", "-s", session, "-f")
