"""
Tests for agent lock feature: locked sessions where agent can only observe.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import RunResult, unique_session_name


class TestLockedSessionStart:
    """Tests for starting sessions with --locked flag."""

    def test_start_with_locked_flag(self, term_cli, tmux_socket):
        """term-cli start -l creates a locked session."""
        session = unique_session_name()
        result = term_cli("start", "-s", session, "-l")
        assert result.ok
        assert "[LOCKED]" in result.stdout
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_start_locked_sets_option(self, term_cli, tmux_socket):
        """Locked session has @term_cli_agent_locked option set."""
        session = unique_session_name()
        term_cli("start", "-s", session, "--locked")
        
        # Check the tmux option directly
        check = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_agent_locked"],
            capture_output=True,
            text=True,
        )
        assert check.stdout.strip() == "1"
        
        # Clean up
        term_cli("kill", "-s", session, "-f")


class TestLockedSessionStatus:
    """Tests for status command on locked sessions."""

    def test_status_shows_locked(self, term_cli, tmux_socket):
        """Status shows Locked: yes for locked sessions."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("status", "-s", session)
        assert result.ok
        assert "Locked: yes" in result.stdout
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_status_shows_unlocked(self, session, term_cli):
        """Status shows Locked: no for unlocked sessions."""
        result = term_cli("status", "-s", session)
        assert result.ok
        assert "Locked: no" in result.stdout


class TestLockedSessionList:
    """Tests for list command with locked sessions."""

    def test_list_shows_locked_indicator(self, term_cli, tmux_socket):
        """List shows [LOCKED] for locked sessions."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("list")
        assert result.ok
        assert f"{session} [LOCKED]" in result.stdout
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_list_no_indicator_for_unlocked(self, session, term_cli):
        """List shows no indicator for unlocked sessions."""
        result = term_cli("list")
        assert result.ok
        # Check that our specific session doesn't have [LOCKED] after it
        for line in result.stdout.splitlines():
            if line.startswith(session):
                assert "[LOCKED]" not in line


class TestLockedCommandsBlocked:
    """Tests for commands that should be blocked on locked sessions."""

    def test_run_blocked_on_locked(self, term_cli, tmux_socket):
        """run command returns exit code 5 on locked session."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("run", "-s", session, "echo hello")
        assert result.returncode == 5
        assert "locked" in result.stderr.lower()
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_send_text_blocked_on_locked(self, term_cli, tmux_socket):
        """send-text command returns exit code 5 on locked session."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("send-text", "-s", session, "hello")
        assert result.returncode == 5
        assert "locked" in result.stderr.lower()
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_send_key_blocked_on_locked(self, term_cli, tmux_socket):
        """send-key command returns exit code 5 on locked session."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("send-key", "-s", session, "Enter")
        assert result.returncode == 5
        assert "locked" in result.stderr.lower()
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_kill_blocked_on_locked(self, term_cli, tmux_socket):
        """kill command returns exit code 5 on locked session."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("kill", "-s", session)
        assert result.returncode == 5
        assert "locked" in result.stderr.lower()
        
        # Force kill for cleanup
        term_cli("kill", "-s", session, "-f")

    def test_resize_blocked_on_locked(self, term_cli, tmux_socket):
        """resize command returns exit code 5 on locked session."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("resize", "-s", session, "-x", "100")
        assert result.returncode == 5
        assert "locked" in result.stderr.lower()
        
        # Clean up
        term_cli("kill", "-s", session, "-f")


class TestAllowedCommandsOnLocked:
    """Tests for commands that should work on locked sessions."""

    def test_capture_allowed_on_locked(self, term_cli, tmux_socket):
        """capture command works on locked sessions."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("capture", "-s", session)
        assert result.ok
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_status_allowed_on_locked(self, term_cli, tmux_socket):
        """status command works on locked sessions."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("status", "-s", session)
        assert result.ok
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_wait_for_allowed_on_locked(self, term_cli, tmux_socket):
        """wait-for command works on locked sessions."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        # Should timeout but not fail with locked error
        result = term_cli("wait-for", "-s", session, "nonexistent", "-t", "0.5")
        assert result.returncode == 3  # Timeout, not locked
        assert "locked" not in result.stderr.lower()
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_request_allowed_on_locked(self, term_cli, tmux_socket):
        """request command works on locked sessions."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_cli("request", "-s", session, "-m", "Need help")
        assert result.ok
        
        # Clean up
        term_cli("kill", "-s", session, "-f")


class TestTermAssistLockUnlock:
    """Tests for term-assist lock and unlock commands."""

    def test_lock_command(self, session, term_cli, term_assist, tmux_socket):
        """term-assist lock locks a session."""
        # Initially unlocked
        status = term_cli("status", "-s", session)
        assert "Locked: no" in status.stdout
        
        # Lock it
        result = term_assist("lock", "-s", session)
        assert result.ok
        assert "Locked" in result.stdout
        
        # Now locked
        status = term_cli("status", "-s", session)
        assert "Locked: yes" in status.stdout

    def test_unlock_command(self, term_cli, term_assist, tmux_socket):
        """term-assist unlock unlocks a session."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        # Initially locked
        status = term_cli("status", "-s", session)
        assert "Locked: yes" in status.stdout
        
        # Unlock it
        result = term_assist("unlock", "-s", session)
        assert result.ok
        assert "Unlocked" in result.stdout
        
        # Now unlocked
        status = term_cli("status", "-s", session)
        assert "Locked: no" in status.stdout
        
        # Clean up
        term_cli("kill", "-s", session)

    def test_lock_already_locked(self, term_cli, term_assist, tmux_socket):
        """term-assist lock on already locked session is idempotent."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        # Lock again
        result = term_assist("lock", "-s", session)
        assert result.ok
        assert "already locked" in result.stdout.lower()
        
        # Clean up
        term_cli("kill", "-s", session, "-f")

    def test_unlock_already_unlocked(self, session, term_cli, term_assist):
        """term-assist unlock on already unlocked session is idempotent."""
        result = term_assist("unlock", "-s", session)
        assert result.ok
        assert "not locked" in result.stdout.lower()


class TestTermAssistListLocked:
    """Tests for term-assist list with locked sessions."""

    def test_list_shows_locked_indicator(self, term_cli, term_assist, tmux_socket):
        """term-assist list shows [LOCKED] for locked sessions."""
        session = unique_session_name()
        term_cli("start", "-s", session, "-l")
        
        result = term_assist("list")
        assert result.ok
        assert "[LOCKED]" in result.stdout
        
        # Clean up
        term_cli("kill", "-s", session, "-f")


class TestTermAssistStartLocked:
    """Tests for term-assist start with --locked flag."""

    def test_start_with_locked_flag(self, term_assist, term_cli, tmux_socket):
        """term-assist start -l creates a locked session."""
        session = unique_session_name()
        result = term_assist("start", "-s", session, "-l")
        assert result.ok
        assert "[LOCKED]" in result.stdout
        
        # Verify it's actually locked
        status = term_cli("status", "-s", session)
        assert "Locked: yes" in status.stdout
        
        # Clean up
        term_cli("kill", "-s", session, "-f")


class TestKillAllWithLocked:
    """Tests for kill --all with locked sessions."""

    def test_kill_all_blocked_by_locked(self, term_cli, tmux_socket):
        """kill --all fails if any session is locked."""
        s1 = unique_session_name()
        s2 = unique_session_name()
        term_cli("start", "-s", s1)
        term_cli("start", "-s", s2, "-l")
        
        result = term_cli("kill", "-a")
        assert result.returncode == 5
        assert "locked" in result.stderr.lower()
        
        # Both sessions should still exist
        list_result = term_cli("list")
        assert s1 in list_result.stdout
        assert s2 in list_result.stdout
        
        # Clean up
        term_cli("kill", "-s", s1)
        term_cli("kill", "-s", s2, "-f")
