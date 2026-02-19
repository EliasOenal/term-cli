"""
Tests for human assistance request commands: request, request-status, request-cancel, request-wait.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from conftest import RunResult, unique_session_name


class TestRequest:
    """Tests for the 'request' command."""

    def test_request_sets_pending(self, session, term_cli):
        """Request command sets a pending request."""
        result = term_cli("request", "-s", session, "-m", "Please help")
        assert result.ok
        assert "request stored" in result.stdout.lower()
        
        # Verify request is pending
        status = term_cli("request-status", "-s", session)
        assert status.ok  # exit 0 means pending

    def test_request_without_message_uses_default(self, session, term_cli):
        """Request command without -m uses default message."""
        result = term_cli("request", "-s", session)
        assert result.ok  # Default message is used
        assert "request stored" in result.stdout.lower()
        
        # Verify request is pending
        status = term_cli("request-status", "-s", session)
        assert status.ok  # exit 0 means pending

    def test_request_nonexistent_session(self, term_cli):
        """Request on nonexistent session fails."""
        result = term_cli("request", "-s", "nonexistent_session_xyz", "-m", "Help")
        assert not result.ok
        assert "not found" in result.stderr.lower() or "does not exist" in result.stderr.lower()


class TestRequestStatus:
    """Tests for the 'request-status' command."""

    def test_request_status_pending(self, session, term_cli):
        """Request-status returns 0 when request is pending."""
        # First make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Check status
        result = term_cli("request-status", "-s", session)
        assert result.returncode == 0  # 0 = pending

    def test_request_status_no_request(self, session, term_cli):
        """Request-status returns 1 when no request is pending, without stderr."""
        # Don't make any request - just check status
        result = term_cli("request-status", "-s", session)
        assert result.returncode == 1  # 1 = no pending request
        assert "none" in result.stdout.lower()
        assert result.stderr == ""  # No error output for a normal query

    def test_request_status_nonexistent_session(self, term_cli):
        """Request-status on nonexistent session fails."""
        result = term_cli("request-status", "-s", "nonexistent_session_xyz")
        assert not result.ok


class TestRequestCancel:
    """Tests for the 'request-cancel' command."""

    def test_request_cancel_removes_request(self, session, term_cli):
        """Request-cancel removes a pending request."""
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Verify it's pending
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 0  # pending
        
        # Cancel it
        result = term_cli("request-cancel", "-s", session)
        assert result.ok
        
        # Verify it's no longer pending
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 1  # not pending

    def test_request_cancel_no_pending_fails(self, session, term_cli):
        """Request-cancel when nothing is pending fails."""
        result = term_cli("request-cancel", "-s", session)
        assert not result.ok  # Should fail when nothing to cancel
        assert "no pending" in result.stderr.lower()

    def test_request_cancel_nonexistent_session(self, term_cli):
        """Request-cancel on nonexistent session fails."""
        result = term_cli("request-cancel", "-s", "nonexistent_session_xyz")
        assert not result.ok


class TestRequestWait:
    """Tests for the 'request-wait' command."""

    def test_request_wait_timeout_no_request(self, session, term_cli):
        """Request-wait fails immediately when no request is pending."""
        result = term_cli("request-wait", "-s", session, "-t", "1")
        assert not result.ok
        assert result.returncode == 2
        assert "no pending" in result.stderr.lower()

    def test_request_wait_returns_immediately_when_already_completed(self, session, term_cli):
        """Request-wait fails if request was already cancelled before wait started."""
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Cancel it immediately (simulating human completing it)
        term_cli("request-cancel", "-s", session)
        
        # Now wait should fail since there's no pending request
        result = term_cli("request-wait", "-s", session, "-t", "2")
        assert not result.ok
        assert "no pending" in result.stderr.lower()

    def test_request_wait_timeout(self, session, term_cli):
        """Request-wait times out if request not completed."""
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Wait with short timeout - should fail
        result = term_cli("request-wait", "-s", session, "-t", "1")
        assert not result.ok
        assert "timeout" in result.stderr.lower() or "timed out" in result.stderr.lower()

    def test_request_wait_nonexistent_session(self, term_cli):
        """Request-wait on nonexistent session fails."""
        result = term_cli("request-wait", "-s", "nonexistent_session_xyz", "-t", "1")
        assert not result.ok


class TestKillWithAttachedClients:
    """Tests for kill command behavior with attached clients."""

    def test_kill_force_flag_exists(self, session, term_cli):
        """Kill command accepts -f/--force flag."""
        # Just test that the flag is accepted
        result = term_cli("kill", "-s", session, "-f")
        assert result.ok

    def test_kill_help_shows_force(self, term_cli):
        """Kill help shows --force option."""
        result = term_cli("kill", "--help")
        assert result.ok
        assert "force" in result.stdout.lower() or "-f" in result.stdout


class TestRequestWorkflow:
    """Integration tests for full request workflow."""

    def test_full_request_cancel_workflow(self, session, term_cli):
        """Test complete workflow: request -> status -> cancel -> status."""
        # Initially no request
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 1
        
        # Make request
        req = term_cli("request", "-s", session, "-m", "Enter password")
        assert req.ok
        assert "request stored" in req.stdout.lower()
        
        # Now pending
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 0
        
        # Cancel
        cancel = term_cli("request-cancel", "-s", session)
        assert cancel.ok
        
        # No longer pending
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 1

    def test_request_message_special_chars(self, session, term_cli):
        """Request message can contain special characters."""
        msg = "Please enter password for user@host: test'quote\"double"
        result = term_cli("request", "-s", session, "-m", msg)
        assert result.ok


class TestResponseMessage:
    """Tests for response message feature (human -> agent communication)."""

    def test_done_with_message_flag(self, session, term_cli, term_assist):
        """term-assist done -m MESSAGE stores response for agent."""
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Complete with response message using -m flag
        result = term_assist("done", "-s", session, "-m", "Done, used password from vault")
        assert result.ok
        
        # Verify request is cleared
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 1  # not pending

    def test_done_with_positional_message(self, session, term_cli, term_assist):
        """term-assist done MESSAGE stores response for agent."""
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Complete with response message as positional argument
        result = term_assist("done", "-s", session, "Task completed successfully")
        assert result.ok
        
        # Verify request is cleared
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 1  # not pending

    def test_done_both_message_args_fails(self, session, term_cli, term_assist):
        """term-assist done -m MSG MSG2 should fail (ambiguous)."""
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Try to complete with both message styles
        result = term_assist("done", "-s", session, "-m", "msg1", "msg2")
        assert not result.ok
        assert "cannot use both" in result.stderr.lower()

    def test_request_wait_receives_response(self, session, term_cli, term_assist, tmux_socket):
        """request-wait prints response message from human."""
        import subprocess
        import threading
        from conftest import TERM_CLI
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please enter password")
        
        # Start request-wait in background
        wait_result = {"stdout": "", "stderr": "", "returncode": None}
        def run_wait():
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["stdout"] = proc.stdout
            wait_result["stderr"] = proc.stderr
            wait_result["returncode"] = proc.returncode
        
        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        
        # Give it a moment to start waiting
        import time
        time.sleep(0.5)
        
        # Complete the request with a response message
        term_assist("done", "-s", session, "-m", "Used password: hunter2")
        
        # Wait for the background thread to finish
        wait_thread.join(timeout=5)
        
        # Verify the response was printed
        assert wait_result["returncode"] == 0
        assert "Response: Used password: hunter2" in wait_result["stdout"]
        assert "Request completed" in wait_result["stdout"]

    def test_request_wait_no_response(self, session, term_cli, term_assist, tmux_socket):
        """request-wait without response message just shows completion."""
        import subprocess
        import threading
        from conftest import TERM_CLI
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please enter password")
        
        # Start request-wait in background
        wait_result = {"stdout": "", "stderr": "", "returncode": None}
        def run_wait():
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["stdout"] = proc.stdout
            wait_result["stderr"] = proc.stderr
            wait_result["returncode"] = proc.returncode
        
        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        
        # Give it a moment to start waiting
        import time
        time.sleep(0.5)
        
        # Complete the request WITHOUT a response message
        term_assist("done", "-s", session)
        
        # Wait for the background thread to finish
        wait_thread.join(timeout=5)
        
        # Verify no response line, just completion
        assert wait_result["returncode"] == 0
        assert "Response:" not in wait_result["stdout"]
        assert "Request completed" in wait_result["stdout"]

    def test_request_cancel_clears_response(self, session, term_cli, tmux_socket):
        """request-cancel also clears any lingering response."""
        import subprocess
        from conftest import TERM_CLI
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Manually set a response (simulating partial completion)
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_response", "test response"],
            capture_output=True,
        )
        
        # Cancel the request
        result = term_cli("request-cancel", "-s", session)
        assert result.ok
        
        # Verify response was also cleared
        check = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_response"],
            capture_output=True,
            text=True,
        )
        assert check.stdout.strip() == ""

    def test_response_with_special_characters(self, session, term_cli, term_assist):
        """Response messages with shell special characters work correctly."""
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Complete with response containing shell special characters
        # These could cause issues if not properly escaped: ! $ ` " ' \
        special_msg = "Done! Used $HOME path & ran `ls`"
        result = term_assist("done", "-s", session, "-m", special_msg)
        assert result.ok
        
        # Verify request is cleared
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 1  # not pending

    def test_done_without_message_clears_stale_response(
        self,
        session,
        term_cli,
        term_assist,
        tmux_socket,
    ):
        """Completing without -m should clear any stale response value."""
        # Seed stale response from a previous request.
        subprocess.run(
            [
                "tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:",
                "@term_cli_response", "stale response",
            ],
            capture_output=True,
        )

        term_cli("request", "-s", session, "-m", "fresh request")
        result = term_assist("done", "-s", session)
        assert result.ok

        check = subprocess.run(
            [
                "tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:",
                "-qv", "@term_cli_response",
            ],
            capture_output=True,
            text=True,
        )
        assert check.stdout.strip() == ""

    def test_request_wait_does_not_emit_stale_response_on_done_without_message(
        self,
        session,
        term_cli,
        term_assist,
        tmux_socket,
    ):
        """A fresh request should not print an old response when done has no message."""
        import threading
        from conftest import TERM_CLI

        # Seed stale response from a previous completed request.
        subprocess.run(
            [
                "tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:",
                "@term_cli_response", "old sensitive value",
            ],
            capture_output=True,
        )

        term_cli("request", "-s", session, "-m", "new request")

        wait_result = {"stdout": "", "stderr": "", "returncode": None}

        def run_wait() -> None:
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["stdout"] = proc.stdout
            wait_result["stderr"] = proc.stderr
            wait_result["returncode"] = proc.returncode

        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        time.sleep(0.5)

        term_assist("done", "-s", session)
        wait_thread.join(timeout=5)

        assert wait_result["returncode"] == 0
        assert "Request completed" in wait_result["stdout"]
        assert "Response:" not in wait_result["stdout"]


class TestMessageIntegrity:
    """Tests to verify messages have no preceding or trailing artifacts."""

    def test_request_message_no_extra_chars(self, session, term_cli, tmux_socket):
        """Request message stored in tmux has no preceding or trailing chars."""
        import subprocess
        
        test_msg = "exact message here"
        term_cli("request", "-s", session, "-m", test_msg)
        
        # Read raw value from tmux
        result = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_request"],
            capture_output=True,
            text=True,
        )
        stored_value = result.stdout.rstrip('\n')  # Only strip the trailing newline from tmux output
        
        assert stored_value == test_msg, f"Expected '{test_msg}', got '{stored_value}'"

    def test_response_message_no_extra_chars(self, session, term_cli, term_assist, tmux_socket):
        """Response message has no preceding or trailing chars in request-wait output."""
        import subprocess
        import threading
        from conftest import TERM_CLI
        
        test_response = "exact response here"
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Start request-wait in background
        wait_result = {"stdout": "", "returncode": None}
        def run_wait():
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["stdout"] = proc.stdout
            wait_result["returncode"] = proc.returncode
        
        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        
        import time
        time.sleep(0.5)
        
        # Complete with exact response
        term_assist("done", "-s", session, "-m", test_response)
        
        wait_thread.join(timeout=5)
        
        # Verify the response line is exactly "Response: <message>" with no extra chars
        assert wait_result["returncode"] == 0
        lines = wait_result["stdout"].strip().split('\n')
        response_line = [l for l in lines if l.startswith("Response:")][0]
        expected_line = f"Response: {test_response}"
        assert response_line == expected_line, f"Expected '{expected_line}', got '{response_line}'"

    def test_response_stored_in_tmux_no_extra_chars(self, session, term_cli, term_assist, tmux_socket):
        """Response stored in tmux option has no preceding or trailing chars."""
        import subprocess
        
        test_response = "exact response value"
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Set response directly via term-assist done
        # But first we need to capture before it's cleared
        # So we'll manually set the option to test what term-cli reads
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_response", test_response],
            capture_output=True,
        )
        
        # Read it back
        result = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_response"],
            capture_output=True,
            text=True,
        )
        stored_value = result.stdout.rstrip('\n')
        
        assert stored_value == test_response, f"Expected '{test_response}', got '{stored_value}'"

    def test_request_message_with_spaces(self, session, term_cli, tmux_socket):
        """Request message with leading/trailing spaces is preserved exactly."""
        import subprocess
        
        test_msg = "  message with spaces  "
        term_cli("request", "-s", session, "-m", test_msg)
        
        result = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_request"],
            capture_output=True,
            text=True,
        )
        stored_value = result.stdout.rstrip('\n')
        
        assert stored_value == test_msg, f"Expected '{test_msg}', got '{stored_value}'"

    def test_response_message_with_spaces(self, session, term_cli, term_assist, tmux_socket):
        """Response message content with internal spaces is preserved."""
        import subprocess
        import threading
        from conftest import TERM_CLI
        
        # Test internal spaces (leading/trailing are stripped by design)
        test_response = "response  with   multiple   spaces"
        
        term_cli("request", "-s", session, "-m", "Please help")
        
        wait_result = {"stdout": ""}
        def run_wait():
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["stdout"] = proc.stdout
        
        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        
        import time
        time.sleep(0.5)
        
        term_assist("done", "-s", session, "-m", test_response)
        
        wait_thread.join(timeout=5)
        
        # The response line should preserve internal spaces
        lines = wait_result["stdout"].strip().split('\n')
        response_line = [l for l in lines if l.startswith("Response:")][0]
        expected_line = f"Response: {test_response}"
        assert response_line == expected_line, f"Expected '{expected_line}', got '{response_line}'"

    def test_no_trailing_percent_in_response(self, session, term_cli, term_assist, tmux_socket):
        """Regression test: response should not have trailing % character."""
        import subprocess
        import threading
        from conftest import TERM_CLI
        
        test_response = "test response"
        
        term_cli("request", "-s", session, "-m", "Please help")
        
        wait_result = {"stdout": ""}
        def run_wait():
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["stdout"] = proc.stdout
        
        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        
        import time
        time.sleep(0.5)
        
        term_assist("done", "-s", session, "-m", test_response)
        
        wait_thread.join(timeout=5)
        
        lines = wait_result["stdout"].strip().split('\n')
        response_line = [l for l in lines if l.startswith("Response:")][0]
        
        # Should NOT end with %
        assert not response_line.endswith('%'), f"Response has trailing %: '{response_line}'"
        # Should be exactly what we expect
        assert response_line == f"Response: {test_response}"


class TestDetachBehavior:
    """Tests for detach behavior - human detaching without completing request."""

    def test_detach_sets_flag_when_request_pending(self, session, term_cli, tmux_socket):
        """Detaching with pending request sets the detached flag."""
        import subprocess
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Simulate what happens when term-assist detach hook runs:
        # Set the detached flag (normally done by the hook)
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_detached", "1"],
            capture_output=True,
        )
        
        # Verify the flag is set
        check = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_detached"],
            capture_output=True,
            text=True,
        )
        assert check.stdout.strip() == "1"
        
        # Request should still be pending
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 0  # still pending

    def test_request_wait_returns_exit_4_on_detach(self, session, term_cli, tmux_socket):
        """request-wait returns exit code 4 when human detaches."""
        import subprocess
        import threading
        from conftest import TERM_CLI
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Start request-wait in background
        wait_result = {"stdout": "", "stderr": "", "returncode": None}
        def run_wait():
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["stdout"] = proc.stdout
            wait_result["stderr"] = proc.stderr
            wait_result["returncode"] = proc.returncode
        
        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        
        # Give it a moment to start waiting
        import time
        time.sleep(0.5)
        
        # Simulate detach by setting the flag
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_detached", "1"],
            capture_output=True,
        )
        
        # Wait for the background thread to finish
        wait_thread.join(timeout=5)
        
        # Verify exit code 4 and message
        assert wait_result["returncode"] == 4
        assert "term-assist detached without response" in wait_result["stdout"]
        # Request should still be pending
        status = term_cli("request-status", "-s", session)
        assert status.returncode == 0  # still pending

    def test_request_wait_can_rewait_after_detach(self, session, term_cli, tmux_socket):
        """After detach, agent can call request-wait again on same request."""
        import subprocess
        import threading
        from conftest import TERM_CLI
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # First: simulate detach
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_detached", "1"],
            capture_output=True,
        )
        
        # First request-wait should return exit 4
        result1 = subprocess.run(
            [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "2"],
            capture_output=True,
            text=True,
        )
        assert result1.returncode == 4
        
        # Second request-wait should block (flag was cleared)
        # We'll complete it with done this time
        wait_result: dict[str, int | str | None] = {"returncode": None, "stdout": None}
        def run_wait():
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["returncode"] = proc.returncode
            wait_result["stdout"] = proc.stdout
        
        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        
        import time
        time.sleep(0.5)
        
        # Clear the request (simulating done)
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-u", "-t", f"={session}:", "@term_cli_request"],
            capture_output=True,
        )
        
        wait_thread.join(timeout=5)
        
        # Should complete successfully this time
        assert wait_result["returncode"] == 0
        stdout = wait_result["stdout"]
        assert isinstance(stdout, str) and "Request completed" in stdout

    def test_done_clears_detached_flag(self, session, term_cli, term_assist, tmux_socket):
        """term-assist done clears any stale detached flag."""
        import subprocess
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Set detached flag (simulating a previous detach)
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_detached", "1"],
            capture_output=True,
        )
        
        # Complete with done
        result = term_assist("done", "-s", session)
        assert result.ok
        
        # Detached flag should be cleared
        check = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_detached"],
            capture_output=True,
            text=True,
        )
        assert check.stdout.strip() == ""

    def test_new_request_clears_detached_flag(self, session, term_cli, tmux_socket):
        """New request clears any stale detached flag from previous request."""
        import subprocess
        
        # Set a stale detached flag
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_detached", "1"],
            capture_output=True,
        )
        
        # Make a new request
        term_cli("request", "-s", session, "-m", "New request")
        
        # Detached flag should be cleared
        check = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_detached"],
            capture_output=True,
            text=True,
        )
        assert check.stdout.strip() == ""

    def test_request_cancel_clears_detached_flag(self, session, term_cli, tmux_socket):
        """request-cancel clears detached flag."""
        import subprocess
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Set detached flag
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_detached", "1"],
            capture_output=True,
        )
        
        # Cancel the request
        result = term_cli("request-cancel", "-s", session)
        assert result.ok
        
        # Detached flag should be cleared
        check = subprocess.run(
            ["tmux", "-L", tmux_socket, "show-option", "-t", f"={session}:", "-qv", "@term_cli_detached"],
            capture_output=True,
            text=True,
        )
        assert check.stdout.strip() == ""

    def test_detach_message_includes_elapsed_time(self, session, term_cli, tmux_socket):
        """Detach message includes elapsed time."""
        import subprocess
        import threading
        import time
        from conftest import TERM_CLI
        
        # Make a request
        term_cli("request", "-s", session, "-m", "Please help")
        
        # Start request-wait in background
        wait_result = {"stdout": ""}
        def run_wait():
            proc = subprocess.run(
                [TERM_CLI, "-L", tmux_socket, "request-wait", "-s", session, "-t", "10"],
                capture_output=True,
                text=True,
            )
            wait_result["stdout"] = proc.stdout
        
        wait_thread = threading.Thread(target=run_wait)
        wait_thread.start()
        
        # Wait a bit so elapsed time is measurable
        time.sleep(1.5)
        
        # Simulate detach
        subprocess.run(
            ["tmux", "-L", tmux_socket, "set-option", "-t", f"={session}:", "@term_cli_detached", "1"],
            capture_output=True,
        )
        
        wait_thread.join(timeout=5)
        
        # Message should include elapsed time like "(1.5s)" or similar
        import re
        assert re.search(r'\(\d+\.\d+s\)', wait_result["stdout"]), \
            f"Expected elapsed time in message, got: {wait_result['stdout']}"
