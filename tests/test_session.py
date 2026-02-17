"""
Tests for session lifecycle commands: start, kill, list, status.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from conftest import RunResult, unique_session_name, wait_for_prompt, TERM_CLI


class TestStart:
    """Tests for the 'start' command."""

    def test_start_creates_session(self, term_cli):
        """Starting a new session creates it successfully."""
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name)
            assert result.ok
            assert f"Created session '{name}'" in result.stdout
            
            # Verify session exists
            list_result = term_cli("list")
            assert name in list_result.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_start_existing_session_fails(self, session, term_cli):
        """Starting an existing session fails with error."""
        result = term_cli("start", "-s", session)
        assert not result.ok
        assert f"Session '{session}' already exists" in result.stderr

    def test_start_with_custom_size(self, term_cli):
        """Starting with custom dimensions works."""
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "-x", "120", "-y", "40")
            assert result.ok
            assert "(120x40)" in result.stdout
            
            # Verify size via status
            status_result = term_cli("status", "-s", name)
            assert "120x40" in status_result.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_start_with_cwd(self, term_cli, tmp_path):
        """Starting with working directory sets cwd."""
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "-c", str(tmp_path))
            assert result.ok
            assert f"in {tmp_path}" in result.stdout
            
            # Verify cwd by running pwd
            term_cli("run", "-s", name, "pwd", "-w")
            capture = term_cli("capture", "-s", name, "-n", "50")
            assert str(tmp_path) in capture.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_start_with_env_vars(self, term_cli):
        """Starting with environment variables makes them available in shell."""
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "-e", "TEST_VAR=hello", "-e", "OTHER_VAR=world")
            assert result.ok
            
            # Wait for shell to be ready, then run commands
            term_cli("wait", "-s", name, "-t", "5")
            term_cli("run", "-s", name, "echo $TEST_VAR", "-w")
            capture = term_cli("capture", "-s", name)
            assert "hello" in capture.stdout
            
            # Test second env var too
            term_cli("run", "-s", name, "echo $OTHER_VAR", "-w")
            capture = term_cli("capture", "-s", name)
            assert "world" in capture.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_start_env_invalid_format(self, term_cli):
        """Environment variable without = raises error and session is not created."""
        name = unique_session_name()
        result = term_cli("start", "-s", name, "-e", "INVALID_NO_EQUALS")
        assert not result.ok
        assert "must be KEY=VALUE" in result.stderr
        
        # Session should not be created since validation happens before
        list_result = term_cli("list")
        assert name not in list_result.stdout

    def test_start_with_shell(self, term_cli):
        """Starting with custom shell uses that shell."""
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "--shell", "/bin/sh")
            assert result.ok
            
            # sh typically has $ prompt, let's just verify session works
            term_cli("run", "-s", name, "echo test", "-w")
            capture = term_cli("capture", "-s", name)
            assert "test" in capture.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_start_no_size_flag(self, term_cli):
        """--no-size lets tmux decide dimensions."""
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "--no-size")
            assert result.ok
            # Should not have size in output - with --no-size, the message
            # should NOT include "(WxH)" at all
            assert f"Created session '{name}'" in result.stdout
            # The normal output would be "Created session 'name' (80x24)" 
            # with --no-size it should be just "Created session 'name'"
            assert "(" not in result.stdout, \
                f"--no-size should not include dimensions in output: {result.stdout}"
        finally:
            term_cli("kill", "-s", name)

    def test_start_session_name_with_dashes(self, term_cli):
        """Session names with dashes work."""
        name = f"test-session-{unique_session_name()}"
        try:
            result = term_cli("start", "-s", name)
            assert result.ok
            assert name in result.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_start_session_name_with_underscores(self, term_cli):
        """Session names with underscores work."""
        name = f"test_session_{unique_session_name()}"
        try:
            result = term_cli("start", "-s", name)
            assert result.ok
            assert name in result.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_start_with_invalid_cwd(self, term_cli):
        """Starting with non-existent cwd fails with validation error."""
        name = unique_session_name()
        result = term_cli("start", "-s", name, "-c", "/nonexistent/path/xyz")
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR (ValueError)
        assert "does not exist" in result.stderr
        # Session should not be created
        list_result = term_cli("list")
        assert name not in list_result.stdout

    def test_start_with_invalid_shell(self, term_cli):
        """Starting with non-existent shell fails with validation error."""
        name = unique_session_name()
        result = term_cli("start", "-s", name, "--shell", "/nonexistent/shell")
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR (ValueError)
        assert "does not exist" in result.stderr
        # Session should not be created
        list_result = term_cli("list")
        assert name not in list_result.stdout

    def test_start_with_non_executable_shell(self, term_cli, tmp_path):
        """Starting with non-executable shell fails with validation error."""
        name = unique_session_name()
        # Create a file that exists but is not executable
        fake_shell = tmp_path / "not_executable"
        fake_shell.write_text("#!/bin/sh\necho hi")
        # Don't set execute permission
        
        result = term_cli("start", "-s", name, "--shell", str(fake_shell))
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR (ValueError)
        assert "not executable" in result.stderr
        # Session should not be created
        list_result = term_cli("list")
        assert name not in list_result.stdout

    def test_start_env_var_empty_value(self, term_cli):
        """Environment variable with empty value works."""
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "-e", "EMPTY_VAR=")
            assert result.ok
            
            # The env var should exist but be empty
            term_cli("wait", "-s", name, "-t", "5")
            term_cli("run", "-s", name, "echo \"value:${EMPTY_VAR}:end\"", "-w")
            capture = term_cli("capture", "-s", name)
            # Should see "value::end" (empty between the colons)
            assert "value::end" in capture.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_start_session_name_special_chars(self, term_cli):
        """Session names with colons are sanitized by tmux."""
        # tmux replaces certain characters (like colons) with underscores
        # because colons are used as separators in tmux target syntax
        name_with_colons = "test_special:char:session"
        expected_name = "test_special_char_session"  # colons become underscores
        
        result = term_cli("start", "-s", name_with_colons)
        assert result.ok
        
        # The session is created with sanitized name
        list_result = term_cli("list")
        assert expected_name in list_result.stdout
        
        # Clean up with the actual name tmux used
        term_cli("kill", "-s", expected_name)


class TestKill:
    """Tests for the 'kill' command."""

    def test_kill_removes_session(self, term_cli):
        """Killing a session removes it."""
        name = unique_session_name()
        term_cli("start", "-s", name, check=True)
        
        result = term_cli("kill", "-s", name)
        assert result.ok
        assert f"Killed session '{name}'" in result.stdout
        
        # Verify session is gone
        list_result = term_cli("list")
        assert name not in list_result.stdout

    def test_kill_nonexistent_session_fails(self, term_cli):
        """Killing a non-existent session fails with error."""
        name = unique_session_name()
        result = term_cli("kill", "-s", name)
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_kill_all_sessions(self, session_factory, term_cli):
        """kill --all removes all sessions."""
        # Create multiple sessions
        s1 = session_factory()
        s2 = session_factory()
        s3 = session_factory()
        
        result = term_cli("kill", "--all")
        assert result.ok
        assert f"Killed session '{s1}'" in result.stdout
        assert f"Killed session '{s2}'" in result.stdout
        assert f"Killed session '{s3}'" in result.stdout
        
        # Verify all gone
        list_result = term_cli("list")
        assert s1 not in list_result.stdout
        assert s2 not in list_result.stdout
        assert s3 not in list_result.stdout

    def test_kill_all_no_sessions(self):
        """kill --all with no sessions prints message."""
        # Use a completely fresh socket that has never had any sessions
        fresh_socket = f"pytest_isolated_{uuid.uuid4().hex[:8]}"
        try:
            result = subprocess.run(
                [str(TERM_CLI), "-L", fresh_socket, "kill", "--all"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0
            assert "No sessions to kill" in result.stdout
        finally:
            # Clean up the socket's tmux server (if it started one)
            subprocess.run(
                ["tmux", "-L", fresh_socket, "kill-server"],
                capture_output=True,
            )

    def test_kill_mutual_exclusion(self, term_cli):
        """Cannot use --session and --all together."""
        result = term_cli("kill", "-s", "foo", "--all")
        assert not result.ok
        assert "Cannot use --all with --session" in result.stderr

    def test_kill_requires_session_or_all(self, term_cli):
        """kill with no arguments fails."""
        result = term_cli("kill")
        assert not result.ok
        assert "Either --session or --all is required" in result.stderr

    def test_kill_all_atomicity(self, tmux_socket: str, session_factory, term_cli):
        """kill --all with one attached session fails without killing any sessions.

        Verifies upfront validation: all sessions are checked for attached clients
        before any are killed, preventing partial kill (where some sessions are
        killed before validation fails on a later session).
        """
        from conftest import retry_until
        # Create two target sessions
        s1 = session_factory()
        s2 = session_factory()

        # Create a helper session and use it to attach to s2,
        # which makes s2 show an attached client
        helper = unique_session_name()
        term_cli("start", "-s", helper, check=True)
        term_cli("wait", "-s", helper, "-t", "10", check=True)
        term_cli("run", "-s", helper, f"TMUX='' tmux -L {tmux_socket} attach -t {s2}")

        try:
            # Wait for the client to register as attached on s2
            def s2_has_client() -> bool:
                res = subprocess.run(
                    ["tmux", "-L", tmux_socket, "display-message", "-p", "-t", f"={s2}:",
                     "#{session_attached}"],
                    capture_output=True, text=True,
                )
                return res.stdout.strip() not in ("", "0")
            assert retry_until(s2_has_client, timeout=5.0), \
                "tmux attach inside helper session did not register a client on s2"

            # kill --all without --force should fail because s2 has an attached client
            result = term_cli("kill", "--all")
            assert not result.ok
            assert "attached" in result.stderr.lower()

            # Both sessions must still be alive (atomicity guarantee)
            list_result = term_cli("list")
            assert s1 in list_result.stdout, f"Session {s1} was killed despite validation failure"
            assert s2 in list_result.stdout, f"Session {s2} was killed despite validation failure"
        finally:
            # Detach the helper's tmux client, then kill the helper session
            term_cli("send-key", "-s", helper, "C-b")
            term_cli("send-key", "-s", helper, "d")
            # Wait for the inner tmux to fully detach (helper returns to shell prompt)
            # so s2 has zero attached clients before session_factory teardown runs
            term_cli("wait", "-s", helper, "-t", "5")
            term_cli("kill", "-s", helper, "-f")


class TestList:
    """Tests for the 'list' command."""

    def test_list_shows_sessions(self, session_factory, term_cli):
        """list shows all active sessions."""
        s1 = session_factory()
        s2 = session_factory()
        
        result = term_cli("list")
        assert result.ok
        assert s1 in result.stdout
        assert s2 in result.stdout

    def test_list_empty(self, term_cli):
        """list with no sessions outputs nothing."""
        # Kill all first
        term_cli("kill", "--all")
        
        result = term_cli("list")
        assert result.ok
        assert result.stdout.strip() == ""

    def test_list_one_per_line(self, session_factory, term_cli):
        """list outputs one session per line."""
        s1 = session_factory()
        s2 = session_factory()
        
        result = term_cli("list")
        lines = [l for l in result.stdout.strip().split("\n") if l.startswith("test_")]
        assert len(lines) >= 2
        assert s1 in lines
        assert s2 in lines


class TestStatus:
    """Tests for the 'status' command."""

    def test_status_shows_session_details(self, session, term_cli):
        """status shows session name, size, state, process tree, etc."""
        result = term_cli("status", "-s", session)
        assert result.ok
        assert f"Session: {session}" in result.stdout
        assert "State:" in result.stdout
        assert "Screen:" in result.stdout
        assert "Size:" in result.stdout
        assert "Processes:" in result.stdout
        # Shell should be in the process tree with a PID
        assert "└─" in result.stdout
        assert "(" in result.stdout and ")" in result.stdout
        assert "Windows:" in result.stdout
        assert "Created:" in result.stdout

    def test_status_nonexistent_session(self, term_cli):
        """status on non-existent session raises error."""
        result = term_cli("status", "-s", "nonexistent_session_xyz")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_status_shows_correct_size(self, term_cli):
        """status shows the size that was set during start."""
        name = unique_session_name()
        try:
            term_cli("start", "-s", name, "-x", "100", "-y", "30", check=True)
            result = term_cli("status", "-s", name)
            assert "100x30" in result.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_status_attached_status(self, session, term_cli):
        """status shows attached status (should be 'no' for test sessions)."""
        result = term_cli("status", "-s", session)
        assert "Attached: no" in result.stdout

    def test_status_shows_idle_when_prompt(self, session, term_cli):
        """status shows state=idle when at shell prompt."""
        # Run a simple command and wait for it to complete
        term_cli("run", "-s", session, "true", "-w", "-t", "5")
        result = term_cli("status", "-s", session)
        # Should be idle - no foreground process beyond the shell
        assert "State: idle" in result.stdout, \
            f"Expected idle state at prompt. Got: {result.stdout}"

    def test_status_shows_running_with_foreground_process(self, session, term_cli):
        """status shows state=running when a foreground process is active."""
        from conftest import retry_until
        # Start a long-running command
        term_cli("run", "-s", session, "sleep 5")
        # Wait for sleep to appear in status
        def check_sleep_running():
            result = term_cli("status", "-s", session)
            return "Foreground: sleep" in result.stdout
        assert retry_until(check_sleep_running, timeout=15.0), "sleep never appeared as foreground process"
        
        result = term_cli("status", "-s", session)
        assert "State: running" in result.stdout
        assert "Foreground: sleep" in result.stdout
        
        # Clean up
        term_cli("send-key", "-s", session, "C-c")

    def test_status_shows_process_tree(self, session, term_cli):
        """status shows process tree with ASCII format and PIDs."""
        from conftest import retry_until
        # Start a nested command that keeps intermediate processes
        term_cli("run", "-s", session, "bash -c 'while true; do sleep 1; done'")
        # Wait for bash to appear in process tree
        def check_bash_running():
            result = term_cli("status", "-s", session)
            return "└─ bash" in result.stdout or "├─ bash" in result.stdout
        assert retry_until(check_bash_running, timeout=15.0), "bash never appeared in process tree"
        
        result = term_cli("status", "-s", session)
        assert "Processes:" in result.stdout
        # Should show tree structure with bash and sleep
        assert "└─ bash" in result.stdout or "├─ bash" in result.stdout
        # Should include PIDs in parentheses
        assert "(" in result.stdout and ")" in result.stdout
        
        # Clean up
        term_cli("send-key", "-s", session, "C-c")

    def test_status_shows_normal_screen_at_shell(self, session, term_cli):
        """status shows Screen: normal when at a shell prompt."""
        term_cli("run", "-s", session, "true", "-w", "-t", "5")
        result = term_cli("status", "-s", session)
        assert result.ok
        assert "Screen: normal" in result.stdout

    def test_status_shows_alternate_screen_in_tui(self, session, term_cli):
        """status shows Screen: alternate when a TUI is running."""
        from conftest import retry_until
        # Use vim (not less /dev/null, which exits immediately with no content)
        term_cli("run", "-s", session, "vim")
        # Poll until vim switches to alternate screen (may take time on slow CI)
        def check_alternate():
            result = term_cli("status", "-s", session)
            return "Screen: alternate" in result.stdout
        assert retry_until(check_alternate, timeout=15.0), \
            "vim never switched to alternate screen"
        # Quit vim
        term_cli("send-text", "-s", session, ":q!", "-e")
        term_cli("wait", "-s", session, "-t", "15")
