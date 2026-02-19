"""
Tests for I/O commands: run, send-text, send-key, send-mouse, send-stdin, capture.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from conftest import TERM_CLI, RunResult, capture_content, retry_until, wait_for_content


class TestRun:
    """Tests for the 'run' command."""

    def test_run_executes_command(self, session, term_cli):
        """run executes a command in the session."""
        term_cli("run", "-s", session, "echo hello world", "-w")
        result = term_cli("capture", "-s", session)
        assert "hello world" in result.stdout

    def test_run_with_wait(self, session, term_cli):
        """run --wait waits for command completion."""
        result = term_cli("run", "-s", session, "echo done", "-w")
        assert result.ok
        assert "Command completed" in result.stdout

    def test_run_with_timeout(self, session, term_cli):
        """run --timeout limits wait time and returns exit code 3."""
        result = term_cli("run", "-s", session, "sleep 10", "-w", "-t", "0.5")
        assert not result.ok
        assert result.returncode == 3  # EXIT_TIMEOUT
        assert "command not completed" in result.stderr
        # Clean up
        term_cli("send-key", "-s", session, "C-c")

    def test_run_without_wait(self, session, term_cli):
        """run without --wait returns immediately."""
        start = time.time()
        result = term_cli("run", "-s", session, "sleep 5")
        elapsed = time.time() - start
        assert result.ok
        assert elapsed < 2  # Should return quickly
        # Clean up the sleep
        term_cli("send-key", "-s", session, "C-c")

    def test_run_nonexistent_session(self, term_cli):
        """run on non-existent session raises error."""
        result = term_cli("run", "-s", "nonexistent_xyz", "echo hi")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_run_command_with_arguments(self, session, term_cli):
        """run handles commands with multiple arguments."""
        term_cli("run", "-s", session, "echo one two three", "-w")
        result = term_cli("capture", "-s", session)
        assert "one two three" in result.stdout

    def test_run_command_with_quotes(self, session, term_cli):
        """run handles commands with quoted strings."""
        term_cli("run", "-s", session, "echo 'hello world'", "-w")
        result = term_cli("capture", "-s", session)
        assert "hello world" in result.stdout

    def test_run_command_with_pipes(self, session, term_cli):
        """run handles commands with pipes."""
        term_cli("run", "-s", session, "echo hello | cat", "-w")
        result = term_cli("capture", "-s", session)
        assert "hello" in result.stdout

    def test_run_command_with_redirects(self, session, term_cli, tmp_path):
        """run handles commands with redirects."""
        from conftest import wait_for_file_content
        from pathlib import Path
        outfile = tmp_path / "out.txt"
        term_cli("run", "-s", session, f"echo redirected > {outfile}", "-w")
        # Wait for file content to appear
        assert wait_for_file_content(Path(outfile), "redirected"), "File content not found"
        assert outfile.exists()
        assert "redirected" in outfile.read_text()

    def test_run_failing_command(self, session, term_cli):
        """run with failing command still completes (shell returns to prompt)."""
        result = term_cli("run", "-s", session, "false", "-w")
        assert result.ok  # term-cli succeeds even if the command fails
        assert "Command completed" in result.stdout

    def test_run_wait_zero_timeout(self, session, term_cli):
        """run --wait --timeout 0 checks once for prompt."""
        # Run a quick command first so prompt is ready
        term_cli("run", "-s", session, "true", "-w")
        # With timeout 0, should detect prompt on first check
        result = term_cli("run", "-s", session, "true", "-w", "-t", "0")
        assert result.ok
        assert "Command completed" in result.stdout

    def test_run_timeout_without_wait_warns(self, session, term_cli):
        """run --timeout without --wait prints a warning."""
        result = term_cli("run", "-s", session, "echo hi", "-t", "5")
        assert result.ok  # Command still succeeds
        assert "no effect without --wait" in result.stderr.lower()


class TestSendText:
    """Tests for the 'send-text' command."""

    def test_send_text_sends_literal(self, session, term_cli):
        """send-text sends literal text."""
        term_cli("send-text", "-s", session, "echo hello")
        # Text should appear but not execute (no Enter).
        # Use capture_content (joined wraps) since the text sits at the
        # prompt and may wrap if the hostname makes the prompt long.
        assert "echo hello" in capture_content(term_cli, session)

    def test_send_text_with_enter(self, session, term_cli):
        """send-text --enter sends text followed by Enter."""
        term_cli("send-text", "-s", session, "echo with_enter", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        result = term_cli("capture", "-s", session)
        assert "with_enter" in result.stdout

    def test_send_text_special_chars(self, session, term_cli):
        """send-text handles special characters."""
        term_cli("send-text", "-s", session, "echo 'quotes' \"double\" `backtick`", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        result = term_cli("capture", "-s", session)
        assert "quotes" in result.stdout

    def test_send_text_unicode(self, session, term_cli):
        """send-text handles unicode characters."""
        term_cli("send-text", "-s", session, "echo 你好世界 🎉", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        result = term_cli("capture", "-s", session)
        assert "你好世界" in result.stdout
        assert "🎉" in result.stdout

    def test_send_text_empty_string(self, session, term_cli):
        """send-text with empty string doesn't error."""
        result = term_cli("send-text", "-s", session, "")
        assert result.ok

    def test_send_text_nonexistent_session(self, term_cli):
        """send-text on non-existent session raises error."""
        result = term_cli("send-text", "-s", "nonexistent_xyz", "hello")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_send_text_multiword(self, session, term_cli):
        """send-text sends multiple words correctly."""
        term_cli("send-text", "-s", session, "echo one two three", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        result = term_cli("capture", "-s", session)
        assert "one two three" in result.stdout


class TestSendKey:
    """Tests for the 'send-key' command."""

    def test_send_key_enter(self, session, term_cli):
        """send-key Enter sends Enter key."""
        term_cli("send-text", "-s", session, "echo keytest")
        term_cli("send-key", "-s", session, "Enter")
        term_cli("wait", "-s", session, "-t", "5")
        result = term_cli("capture", "-s", session)
        assert "keytest" in result.stdout

    def test_send_key_ctrl_c(self, session, term_cli):
        """send-key C-c sends Ctrl+C and interrupts running process."""
        term_cli("run", "-s", session, "sleep 100")
        # Wait for sleep to start
        def check_sleep_running():
            result = term_cli("status", "-s", session)
            return "sleep" in result.stdout
        assert retry_until(check_sleep_running, timeout=15.0), "sleep never started"
        term_cli("send-key", "-s", session, "C-c")
        # Process should be interrupted - wait should detect prompt
        result = term_cli("wait", "-s", session, "-t", "5")
        assert "Prompt detected" in result.stdout, \
            "Ctrl+C should have interrupted process and returned to prompt"

    def test_send_key_ctrl_d(self, session, term_cli):
        """send-key C-d sends Ctrl+D (EOF) and terminates cat."""
        # Start cat which waits for input
        term_cli("run", "-s", session, "cat")
        # Wait for cat to start
        def check_cat_running():
            result = term_cli("status", "-s", session)
            return "cat" in result.stdout
        assert retry_until(check_cat_running, timeout=15.0), "cat never started"
        term_cli("send-key", "-s", session, "C-d")
        # cat should have exited - wait should detect prompt
        result = term_cli("wait", "-s", session, "-t", "5")
        assert "Prompt detected" in result.stdout, \
            "Ctrl+D should have sent EOF and cat should have exited"

    def test_send_key_arrow_up(self, session, term_cli):
        """send-key Up sends up arrow (command history)."""
        term_cli("run", "-s", session, "echo first", "-w")
        term_cli("send-key", "-s", session, "Up")
        assert wait_for_content(term_cli, session, "echo first"), "Up arrow didn't recall command"
        # Up arrow should recall "echo first" (use joined wraps — text is at prompt)
        assert "echo first" in capture_content(term_cli, session)

    def test_send_key_arrow_keys(self, session, term_cli):
        """send-key handles all arrow keys."""
        for key in ["Up", "Down", "Left", "Right"]:
            result = term_cli("send-key", "-s", session, key)
            assert result.ok

    def test_send_key_escape(self, session, term_cli):
        """send-key Escape sends Escape key."""
        result = term_cli("send-key", "-s", session, "Escape")
        assert result.ok

    def test_send_key_tab(self, session, term_cli, tmp_path):
        """send-key Tab sends Tab and triggers completion."""
        # Create a unique file for tab completion
        unique_file = tmp_path / "tabtest_unique_file.txt"
        unique_file.write_text("test")
        
        # cd to tmp_path and try to complete
        term_cli("run", "-s", session, f"cd {tmp_path}", "-w")
        term_cli("send-text", "-s", session, "cat tabtest_uni")
        term_cli("send-key", "-s", session, "Tab")
        assert wait_for_content(term_cli, session, "tabtest_unique_file.txt"), "Tab completion didn't work"
        # Tab completion should complete to the full filename
        # (use joined wraps — completed text is at the prompt)
        output = capture_content(term_cli, session)
        assert "tabtest_unique_file.txt" in output, \
            f"Tab completion should have completed the filename: {output}"
        # Clean up - send Ctrl+C to cancel
        term_cli("send-key", "-s", session, "C-c")

    def test_send_key_backspace(self, session, term_cli):
        """send-key BSpace sends backspace and deletes characters."""
        # Use a unique string to avoid matching prompt contents
        term_cli("send-text", "-s", session, "XYZZY")
        assert wait_for_content(term_cli, session, "XYZZY"), "Text wasn't sent"
        term_cli("send-key", "-s", session, "BSpace")
        term_cli("send-key", "-s", session, "BSpace")
        # Wait for backspace to take effect - should see XYZ but not XYZZY.
        # Use capture_content (joined wraps) since text is at the prompt.
        def check_backspace_worked():
            output = capture_content(term_cli, session)
            return "XYZ" in output and "XYZZY" not in output
        assert retry_until(check_backspace_worked, timeout=15.0), "Backspace didn't delete characters"
        output = capture_content(term_cli, session)
        # Should have "XYZ" not "XYZZY" - backspace deleted 2 chars
        assert "XYZ" in output
        # The full "XYZZY" should not appear anywhere (backspace deleted "ZY")
        assert "XYZZY" not in output, \
            f"Backspace should have deleted characters. Output: {output}"

    def test_send_key_function_keys(self, session, term_cli):
        """send-key handles function keys F1-F12."""
        for i in range(1, 13):
            result = term_cli("send-key", "-s", session, f"F{i}")
            assert result.ok

    def test_send_key_nonexistent_session(self, term_cli):
        """send-key on non-existent session raises error."""
        result = term_cli("send-key", "-s", "nonexistent_xyz", "Enter")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_send_key_invalid_key_name(self, session, term_cli):
        """send-key with invalid key name sends it as literal text."""
        # tmux treats unrecognized key names as literal text
        result = term_cli("send-key", "-s", session, "NotARealKey")
        assert result.ok
        
        # The literal text should appear in the terminal
        assert wait_for_content(term_cli, session, "NotARealKey"), "Literal text wasn't sent"
        # Use joined wraps — text is at the prompt
        assert "NotARealKey" in capture_content(term_cli, session)


class TestSendMouse:
    """Tests for the 'send-mouse' command."""

    def _start_less(self, session: str, term_cli: Callable[..., RunResult], text: str) -> None:
        term_cli("send-text", "-s", session, f"printf {text!r} | less", "-e")

        def in_alternate() -> bool:
            status = term_cli("status", "-s", session)
            return "Screen: alternate" in status.stdout

        assert retry_until(in_alternate, timeout=15.0), "less did not enter alternate screen"

    def _quit_less(self, session: str, term_cli: Callable[..., RunResult]) -> None:
        term_cli("send-key", "-s", session, "q")
        term_cli("wait", "-s", session, "-t", "5")

    def test_send_mouse_requires_alternate_screen(self, session, term_cli):
        """send-mouse fails on normal shell screen."""
        result = term_cli("send-mouse", "-s", session, "--x", "0", "--y", "0")
        assert not result.ok
        assert "alternate" in result.stderr.lower()

    def test_send_mouse_text_click_in_alternate_screen(self, session, term_cli):
        """send-mouse --text works in alternate screen mode."""
        self._start_less(session, term_cli, "line1\\nline2\\nline3\\n")
        try:
            result = term_cli("send-mouse", "-s", session, "--text", "line2")
            assert result.ok
        finally:
            self._quit_less(session, term_cli)

    def test_send_mouse_text_ambiguous_requires_nth(self, session, term_cli):
        """send-mouse --text fails with guidance when multiple matches exist."""
        self._start_less(session, term_cli, "OK\\nvalue\\nOK\\n")
        try:
            result = term_cli("send-mouse", "-s", session, "--text", "OK")
            assert not result.ok
            assert "--nth" in result.stderr
            assert "matched" in result.stderr
        finally:
            self._quit_less(session, term_cli)

    def test_send_mouse_text_nth_disambiguates(self, session, term_cli):
        """send-mouse --text with --nth selects one of multiple matches."""
        self._start_less(session, term_cli, "OK\\nvalue\\nOK\\n")
        try:
            result = term_cli("send-mouse", "-s", session, "--text", "OK", "--nth", "2")
            assert result.ok
        finally:
            self._quit_less(session, term_cli)

    def test_send_mouse_scroll_down_on_text_position(self, session, term_cli):
        """send-mouse --scroll-down can target a --text position."""
        lines = "\\n".join(f"line{i}" for i in range(1, 80)) + "\\n"
        self._start_less(session, term_cli, lines)
        try:
            result = term_cli("send-mouse", "-s", session, "--text", "line20", "--scroll-down")
            assert result.ok
        finally:
            self._quit_less(session, term_cli)

    def test_send_mouse_scroll_up_with_repeat_value(self, session, term_cli):
        """send-mouse supports --scroll-up N syntax."""
        lines = "\\n".join(f"line{i}" for i in range(1, 80)) + "\\n"
        self._start_less(session, term_cli, lines)
        try:
            result = term_cli("send-mouse", "-s", session, "--text", "line20", "--scroll-up", "3")
            assert result.ok
        finally:
            self._quit_less(session, term_cli)

    def test_send_mouse_scroll_short_flags(self, session, term_cli):
        """send-mouse supports -u/-d short flags for scrolling."""
        lines = "\\n".join(f"line{i}" for i in range(1, 80)) + "\\n"
        self._start_less(session, term_cli, lines)
        try:
            down = term_cli("send-mouse", "-s", session, "--text", "line20", "-d", "2")
            up = term_cli("send-mouse", "-s", session, "--text", "line20", "-u")
            assert down.ok
            assert up.ok
        finally:
            self._quit_less(session, term_cli)

    def test_send_mouse_with_encoding_override(self, session, term_cli):
        """send-mouse accepts explicit --mouse-encoding override."""
        self._start_less(session, term_cli, "line1\\nline2\\nline3\\n")
        try:
            result = term_cli(
                "send-mouse", "-s", session,
                "--text", "line2",
                "--mouse-encoding", "sgr",
            )
            assert result.ok
        finally:
            self._quit_less(session, term_cli)

    def test_send_mouse_rejects_scroll_button_value(self, session, term_cli):
        """send-mouse no longer accepts scroll buttons."""
        self._start_less(session, term_cli, "line1\\nline2\\n")
        try:
            result = term_cli(
                "send-mouse", "-s", session,
                "--text", "line1",
                "--button", "scroll-down",
            )
            assert not result.ok
            assert "invalid choice" in result.stderr.lower()
        finally:
            self._quit_less(session, term_cli)

class TestCapture:
    """Tests for the 'capture' command."""

    def test_capture_visible_screen(self, session, term_cli):
        """capture returns visible screen content."""
        term_cli("run", "-s", session, "echo visible_content", "-w")
        result = term_cli("capture", "-s", session)
        assert result.ok
        assert "visible_content" in result.stdout

    def test_capture_trims_by_default(self, session, term_cli):
        """capture trims trailing whitespace by default."""
        term_cli("run", "-s", session, "echo test", "-w")
        result = term_cli("capture", "-s", session)
        # Should not have trailing newlines beyond content
        assert not result.stdout.endswith("\n\n\n")

    def test_capture_no_trim(self, session, term_cli):
        """capture --no-trim preserves trailing whitespace."""
        term_cli("run", "-s", session, "echo test", "-w")
        
        # Capture with trim (default)
        result_trim = term_cli("capture", "-s", session)
        # Capture without trim
        result_no_trim = term_cli("capture", "-s", session, "--no-trim")
        
        assert result_no_trim.ok
        # With no-trim, we get the full pane including blank lines,
        # so it should be longer than trimmed output
        assert len(result_no_trim.stdout) > len(result_trim.stdout), \
            f"--no-trim output ({len(result_no_trim.stdout)} chars) should be longer than trimmed ({len(result_trim.stdout)} chars)"

    def test_capture_with_scrollback(self, session, term_cli):
        """capture --scrollback includes scrollback history."""
        # Generate enough output to scroll
        for i in range(30):
            term_cli("run", "-s", session, f"echo line_{i}", "-w")
        
        # Request enough scrollback to include early lines even with long prompts
        # macOS CI has ~80 char prompts, so each command can take 3-4 lines
        result = term_cli("capture", "-s", session, "-n", "200")
        assert result.ok
        # Should see early lines from scrollback
        assert "line_0" in result.stdout, \
            f"Scrollback should include early lines. Got: {result.stdout[:500]}"
        # And also later lines
        assert "line_29" in result.stdout

    def test_capture_scrollback_rejected_in_alternate_screen(self, session, term_cli):
        """capture --scrollback fails in alternate screen unless forced."""
        term_cli("send-text", "-s", session, "echo -e 'line1\\nline2' | less", "-e")

        def in_alternate() -> bool:
            status = term_cli("status", "-s", session)
            return "Screen: alternate" in status.stdout

        assert retry_until(in_alternate, timeout=15.0), "less did not enter alternate screen"
        try:
            result = term_cli("capture", "-s", session, "-n", "50")
            assert not result.ok
            assert result.returncode == 2
            assert "alternate screen" in result.stderr.lower()
            assert "--force" in result.stderr
        finally:
            term_cli("send-key", "-s", session, "q")
            term_cli("wait", "-s", session, "-t", "5")

    def test_capture_scrollback_force_allows_alternate_screen(self, session, term_cli):
        """capture --scrollback --force allows capture in alternate screen."""
        term_cli("send-text", "-s", session, "echo -e 'line1\\nline2' | less", "-e")

        def in_alternate() -> bool:
            status = term_cli("status", "-s", session)
            return "Screen: alternate" in status.stdout

        assert retry_until(in_alternate, timeout=15.0), "less did not enter alternate screen"
        try:
            result = term_cli("capture", "-s", session, "-n", "50", "--force")
            assert result.ok
        finally:
            term_cli("send-key", "-s", session, "q")
            term_cli("wait", "-s", session, "-t", "5")

    def test_capture_empty_screen(self, term_cli):
        """capture on fresh session works."""
        from conftest import unique_session_name
        name = unique_session_name()
        try:
            term_cli("start", "-s", name, check=True)
            term_cli("wait", "-s", name, "-t", "5")  # Wait for shell to initialize
            result = term_cli("capture", "-s", name)
            assert result.ok
        finally:
            term_cli("kill", "-s", name)

    def test_capture_nonexistent_session(self, term_cli):
        """capture on non-existent session raises error."""
        result = term_cli("capture", "-s", "nonexistent_xyz")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_capture_multiline_output(self, session, term_cli):
        """capture handles multiline output."""
        term_cli("run", "-s", session, "echo -e 'line1\\nline2\\nline3'", "-w")
        result = term_cli("capture", "-s", session)
        assert "line1" in result.stdout
        assert "line2" in result.stdout
        assert "line3" in result.stdout

    def test_capture_long_lines(self, session, term_cli):
        """capture handles long lines that might wrap."""
        long_text = "x" * 200
        term_cli("run", "-s", session, f"echo {long_text}", "-w")
        result = term_cli("capture", "-s", session)
        # Content should be present, might be wrapped
        assert "xxx" in result.stdout

    def test_capture_colored_output(self, session, term_cli):
        """capture handles colored output (ANSI codes)."""
        # Use printf with ANSI codes for color
        term_cli("run", "-s", session, "printf '\\033[31mred\\033[0m'", "-w")
        result = term_cli("capture", "-s", session)
        # The word "red" should be there (codes might be stripped by tmux)
        assert "red" in result.stdout

    def test_capture_scrollback_zero_errors(self, session, term_cli):
        """capture --scrollback 0 fails with a validation error."""
        term_cli("run", "-s", session, "echo test", "-w")
        result = term_cli("capture", "-s", session, "-n", "0")
        assert not result.ok
        assert result.returncode == 2
        assert "positive" in result.stderr.lower()

    def test_capture_scrollback_large_number(self, session, term_cli):
        """capture --scrollback with large number works."""
        term_cli("run", "-s", session, "echo test", "-w")
        result = term_cli("capture", "-s", session, "-n", "10000")
        assert result.ok
        assert "test" in result.stdout

    def test_capture_scrollback_negative_errors(self, session, term_cli):
        """capture --scrollback with negative value fails with validation error."""
        result = term_cli("capture", "-s", session, "-n", "-5")
        assert not result.ok
        assert result.returncode == 2
        assert "positive" in result.stderr.lower()

    def test_capture_scrollback_truncates_to_n_lines(self, session, term_cli):
        """capture --scrollback N returns at most N logical lines."""
        # Generate plenty of output
        for i in range(30):
            term_cli("run", "-s", session, f"echo sbtrunc_{i}", "-w")

        result = term_cli("capture", "-s", session, "-n", "5")
        assert result.ok
        lines = result.stdout.strip().split('\n')
        assert len(lines) <= 5, \
            f"--scrollback 5 should return at most 5 lines, got {len(lines)}: {lines}"

    def test_capture_tail(self, session, term_cli):
        """capture --tail N returns last N physical rows from visible screen."""
        # Put some content on screen
        term_cli("run", "-s", session, "echo tail_test_line", "-w")
        result = term_cli("capture", "-s", session, "-t", "3")
        assert result.ok
        lines = result.stdout.strip().split('\n')
        assert len(lines) <= 3, \
            f"--tail 3 should return at most 3 lines, got {len(lines)}: {lines}"

    def test_capture_tail_zero_errors(self, session, term_cli):
        """capture --tail 0 fails with validation error."""
        result = term_cli("capture", "-s", session, "-t", "0")
        assert not result.ok
        assert result.returncode == 2
        assert "positive" in result.stderr.lower()

    def test_capture_tail_negative_errors(self, session, term_cli):
        """capture --tail with negative value fails with validation error."""
        result = term_cli("capture", "-s", session, "-t", "-3")
        assert not result.ok
        assert result.returncode == 2
        assert "positive" in result.stderr.lower()

    def test_capture_scrollback_and_tail_mutually_exclusive(self, session, term_cli):
        """capture --scrollback and --tail together fails with validation error."""
        result = term_cli("capture", "-s", session, "-n", "50", "-t", "5")
        assert not result.ok
        assert result.returncode == 2
        assert "mutually exclusive" in result.stderr.lower()

    def test_capture_raw_includes_ansi_codes(self, session, term_cli):
        """capture --raw includes ANSI escape codes."""
        # Use printf to output colored text
        term_cli("run", "-s", session, "printf '\\033[31mRED\\033[0m'", "-w")
        
        # Default capture strips ANSI codes from the OUTPUT
        result_default = term_cli("capture", "-s", session)
        assert result_default.ok
        assert "RED" in result_default.stdout
        
        # Raw capture includes ANSI codes
        result_raw = term_cli("capture", "-s", session, "-r")
        assert result_raw.ok
        assert "RED" in result_raw.stdout
        # Raw output should be longer due to escape codes
        # (The codes appear in the actual colored output, not just the command)
        # tmux outputs escape codes when -e flag is used
        assert len(result_raw.stdout) >= len(result_default.stdout)

    def test_capture_raw_short_flag(self, session, term_cli):
        """-r works as short form for --raw."""
        term_cli("run", "-s", session, "printf '\\033[32mGREEN\\033[0m'", "-w")
        
        result = term_cli("capture", "-s", session, "-r")
        assert result.ok
        # Should contain color codes
        assert "[32m" in result.stdout or "\033[32m" in result.stdout

    def test_capture_raw_with_scrollback(self, session, term_cli):
        """capture --raw --scrollback includes ANSI codes in scrollback."""
        # Generate colored output
        term_cli("run", "-s", session, "printf '\\033[33mYELLOW\\033[0m'", "-w")
        term_cli("run", "-s", session, "echo more_lines", "-w")
        
        result = term_cli("capture", "-s", session, "-r", "-n", "50")
        assert result.ok
        assert "YELLOW" in result.stdout
        # Should have escape codes
        assert "[33m" in result.stdout or "\033[33m" in result.stdout

    def test_capture_raw_with_no_trim(self, session, term_cli):
        """capture --raw --no-trim combines both flags."""
        term_cli("run", "-s", session, "printf '\\033[34mBLUE\\033[0m'", "-w")
        
        # Capture with both flags
        result = term_cli("capture", "-s", session, "-r", "--no-trim")
        assert result.ok
        assert "BLUE" in result.stdout
        # Should have escape codes
        assert "[34m" in result.stdout or "\033[34m" in result.stdout
        # Should have trailing content (not trimmed) - longer than trimmed
        result_trimmed = term_cli("capture", "-s", session, "-r")
        assert len(result.stdout) >= len(result_trimmed.stdout)

    def test_capture_raw_multiple_colors(self, session, term_cli):
        """capture --raw handles multiple color codes."""
        term_cli("run", "-s", session, 
                 "printf '\\033[31mR\\033[32mG\\033[34mB\\033[0m'", "-w")
        
        result = term_cli("capture", "-s", session, "-r")
        assert result.ok
        # All three colors should be present
        assert "R" in result.stdout and "G" in result.stdout and "B" in result.stdout
        # Should have multiple color codes
        color_codes = ["[31m", "[32m", "[34m"]
        found_codes = sum(1 for code in color_codes if code in result.stdout)
        assert found_codes >= 2, f"Expected multiple color codes, found {found_codes}"

    def test_capture_raw_preserves_reset_codes(self, session, term_cli):
        """capture --raw preserves reset/clear codes."""
        term_cli("run", "-s", session, "printf '\\033[1mbold\\033[0m normal'", "-w")
        
        result = term_cli("capture", "-s", session, "-r")
        assert result.ok
        assert "bold" in result.stdout
        assert "normal" in result.stdout
        # Should have bold code [1m and reset code [0m or [39m
        assert "[1m" in result.stdout or "\033[1m" in result.stdout

    def test_capture_default_strips_codes_clean(self, session, term_cli):
        """Default capture produces clean text output."""
        term_cli("run", "-s", session, 
                 "printf '\\033[31;1;4mformatted\\033[0m plain'", "-w")
        
        result = term_cli("capture", "-s", session)
        assert result.ok
        assert "formatted" in result.stdout
        assert "plain" in result.stdout
        # The output text should be readable
        # (Command line will contain the escape sequences as literal text,
        # but the actual rendered output should be clean)

    def test_capture_preserves_physical_line_breaks(self, session_factory, term_cli):
        """Plain capture preserves physical row breaks; scrollback joins them.

        Verifies the rendering contract:
        - Plain capture returns physical screen rows, so text that wraps at
          the terminal width is split across lines.
        - Scrollback capture (--scrollback / -J) joins wrapped lines back
          into logical lines.

        Uses a controlled terminal width (40 cols) and deterministic fill
        patterns so the test is immune to prompt length or hostname.
        """
        session = session_factory(cols=40)

        # Pattern that fits in one row (30 chars < 40 cols)
        short = "1234567890" * 3  # 30 chars
        # Pattern that must wrap (60 chars > 40 cols)
        long = "1234567890" * 6   # 60 chars

        # Print both patterns on their own lines (printf avoids echo portability issues)
        term_cli("run", "--session", session, f"printf '%s\\n%s\\n' '{short}' '{long}'", "--wait")

        # --- Plain capture: physical rows preserved ---
        result = term_cli("capture", "--session", session)
        assert result.ok
        lines = result.stdout.split("\n")

        # The 30-char pattern must appear as a single contiguous line
        assert short in lines, (
            f"Short pattern should appear as one physical row.\n"
            f"Lines: {lines}"
        )

        # The 60-char pattern must NOT appear as a contiguous substring —
        # it is split by a newline at column 40
        assert long not in result.stdout, (
            f"Long pattern should be split across physical rows.\n"
            f"Output: {result.stdout!r}"
        )

        # Verify the split: first 40 chars on one row, remaining 20 on the next
        first_half = long[:40]
        second_half = long[40:]
        assert first_half in lines, (
            f"First 40 chars of long pattern should be a physical row.\n"
            f"Lines: {lines}"
        )
        assert second_half in lines, (
            f"Remaining 20 chars of long pattern should be on the next row.\n"
            f"Lines: {lines}"
        )

        # --- Scrollback capture: wraps joined ---
        result_joined = term_cli("capture", "--session", session, "--scrollback", "500")
        assert result_joined.ok

        # The 60-char pattern must appear as a contiguous substring now
        assert long in result_joined.stdout, (
            f"Scrollback capture should join the wrapped line.\n"
            f"Output: {result_joined.stdout!r}"
        )


    # ==================== Annotate ====================

    def test_capture_annotate_default_no_numbered_content_lines(self, session, term_cli):
        """capture --annotate does not number visible lines by default."""
        term_cli("run", "-s", session, "echo annotate_test", "-w")
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        assert "annotate_test" in result.stdout

        content_part = result.stdout.split("Annotations:", 1)[0]
        assert not re.search(r"^\s*\d+│ ", content_part, re.MULTILINE)

    def test_capture_annotate_line_numbers_enabled(self, session, term_cli):
        """capture --annotate --line-numbers prints 1-based row prefixes."""
        term_cli("run", "-s", session, "echo annotate_test", "-w")
        result = term_cli("capture", "-s", session, "-a", "--line-numbers")
        assert result.ok
        content_part = result.stdout.split("Annotations:", 1)[0]
        first_match = re.search(r"^\s*(\d+)│ ", content_part, re.MULTILINE)
        assert first_match is not None
        assert int(first_match.group(1)) >= 1

    def test_capture_line_numbers_plain_mode(self, session, term_cli):
        """capture --line-numbers works without --annotate."""
        term_cli("run", "-s", session, "printf 'alpha\\nbeta\\n'", "-w")
        result = term_cli("capture", "-s", session, "--line-numbers")
        assert result.ok
        assert re.search(r"^\s*1│ ", result.stdout, re.MULTILINE)

    def test_capture_line_numbers_scrollback_incompatible(self, session, term_cli):
        """capture --line-numbers with --scrollback fails validation."""
        result = term_cli("capture", "-s", session, "--line-numbers", "--scrollback", "10")
        assert not result.ok
        assert result.returncode == 2
        assert "line-numbers" in result.stderr.lower()

    def test_capture_default_no_annotations_on_normal_screen(self, session, term_cli):
        """Default capture on normal screen stays plain (no annotations section)."""
        term_cli("run", "-s", session, "echo plain_capture", "-w")
        result = term_cli("capture", "-s", session)
        assert result.ok
        assert "plain_capture" in result.stdout
        assert "Annotations:" not in result.stdout

    def test_capture_default_auto_annotations_on_active_alternate_screen(self, session, term_cli):
        """Default capture auto-enables annotations for active TUIs."""
        term_cli("send-text", "-s", session, "echo -e 'line1\\nline2' | less", "-e")

        def in_alternate() -> bool:
            status = term_cli("status", "-s", session)
            return "Screen: alternate" in status.stdout

        assert retry_until(in_alternate, timeout=15.0), "less did not enter alternate screen"
        try:
            result = term_cli("capture", "-s", session)
            assert result.ok
            assert "Annotations:" in result.stdout
            assert "Screen: alternate" in result.stdout
        finally:
            term_cli("send-key", "-s", session, "q")
            term_cli("wait", "-s", session, "-t", "5")

    def test_capture_no_annotate_overrides_auto_alternate_mode(self, session, term_cli):
        """--no-annotate forces plain output even during active TUIs."""
        term_cli("send-text", "-s", session, "echo -e 'line1\\nline2' | less", "-e")

        def in_alternate() -> bool:
            status = term_cli("status", "-s", session)
            return "Screen: alternate" in status.stdout

        assert retry_until(in_alternate, timeout=15.0), "less did not enter alternate screen"
        try:
            result = term_cli("capture", "-s", session, "--no-annotate")
            assert result.ok
            assert "Annotations:" not in result.stdout
        finally:
            term_cli("send-key", "-s", session, "q")
            term_cli("wait", "-s", session, "-t", "5")

    def test_capture_annotate_cursor_position(self, session, term_cli):
        """capture --annotate includes cursor position in annotations."""
        term_cli("run", "-s", session, "echo cursor_test", "-w")
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        assert "Annotations:" in result.stdout
        # Cursor line should be present with 1-based row,col format
        assert "Cursor: " in result.stdout
        # Parse cursor line to verify format
        cursor_match = re.search(r"Cursor: (\d+),(\d+)", result.stdout)
        assert cursor_match is not None
        row = int(cursor_match.group(1))
        col = int(cursor_match.group(2))
        assert row >= 1
        assert col >= 1

    def test_capture_annotate_no_false_positives_on_plain_text(self, session, term_cli):
        """capture --annotate on plain shell output produces no highlight annotations."""
        term_cli("run", "-s", session, "echo hello world", "-w")
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        # Annotations section is always present (at minimum cursor)
        assert "Annotations:" in result.stdout
        assert "Cursor:" in result.stdout
        # No Row annotations should be present for plain text
        assert "Row " not in result.stdout

    def test_capture_annotate_bell(self, session, term_cli):
        """capture --annotate detects bell and clears the flag."""
        term_cli("run", "-s", session, r"printf '\a'", "-w")
        # First capture should show bell
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        assert "Bell: yes (cleared)" in result.stdout
        # Second capture should NOT show bell (it was cleared)
        result2 = term_cli("capture", "-s", session, "-a")
        assert result2.ok
        assert "Bell:" not in result2.stdout

    def test_capture_annotate_no_bell_when_not_rung(self, session, term_cli):
        """capture --annotate omits bell line when no bell was rung."""
        term_cli("run", "-s", session, "echo no_bell", "-w")
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        assert "Bell:" not in result.stdout

    def test_capture_annotate_alternate_screen(self, session, term_cli):
        """capture --annotate shows Screen: alternate when a TUI is active."""
        # Start less (enters alternate screen)
        term_cli("send-text", "-s", session,
                 "echo -e 'line1\\nline2' | less", "-e")

        def in_alternate() -> bool:
            status = term_cli("status", "-s", session)
            return "Screen: alternate" in status.stdout

        assert retry_until(in_alternate, timeout=15.0), "less did not enter alternate screen"
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        assert "Screen: alternate" in result.stdout
        # Quit less
        term_cli("send-key", "-s", session, "q")
        term_cli("wait", "-s", session, "-t", "5")
        # After quitting, alternate screen should not be shown
        result2 = term_cli("capture", "-s", session, "-a")
        assert result2.ok
        assert "Screen: alternate" not in result2.stdout

    def test_capture_annotate_metadata_ordering(self, session, term_cli):
        """capture --annotate metadata appears in order: cursor before highlights."""
        # Create a highlight so we have both types
        term_cli("run", "-s", session,
                 r"printf '\033[42m  HIGHLIGHTED_ITEM  \033[0m\n'", "-w")
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        stdout = result.stdout
        cursor_pos = stdout.find("Cursor:")
        # Highlights now use the same "NNN│" line-number prefix as screen lines
        anno_pos = stdout.find("Annotations:")
        assert anno_pos != -1
        # Find first "│" line after Annotations: that contains a bg: label
        after_anno = stdout[anno_pos:]
        highlight_offset = after_anno.find("[bg:")
        assert highlight_offset != -1, "Expected a highlight annotation"
        row_pos = anno_pos + highlight_offset
        # Cursor before highlights
        assert cursor_pos < row_pos, "Cursor should come before highlight annotations"

    def test_capture_annotate_detects_colored_bg(self, session, term_cli):
        """capture --annotate detects text with colored background."""
        # Use printf to output text with a colored background (green bg)
        # This creates a non-structural highlight on a single line
        term_cli("run", "-s", session,
                 r"printf '\033[42m  HIGHLIGHTED  \033[0m\n'", "-w")
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        assert "│" in result.stdout
        # The green-bg text should produce an annotation
        assert "Annotations:" in result.stdout
        assert "HIGHLIGHTED" in result.stdout

    def test_capture_annotate_detects_reverse_video(self, session, term_cli):
        """capture --annotate detects reverse-video highlights."""
        # Reverse video is the most common TUI highlight pattern
        term_cli("run", "-s", session,
                 r"printf '\033[7m  SELECTED  \033[0m\n'", "-w")
        result = term_cli("capture", "-s", session, "-a")
        assert result.ok
        assert "Annotations:" in result.stdout
        assert "SELECTED" in result.stdout
        # Reverse video is resolved to a concrete bg color
        assert "bg:" in result.stdout.lower()

    def test_capture_annotate_raw_mutually_exclusive(self, session, term_cli):
        """capture --annotate and --raw are mutually exclusive."""
        result = term_cli("capture", "-s", session, "-a", "-r")
        assert not result.ok
        assert result.returncode == 2

    def test_capture_annotate_scrollback_incompatible(self, session, term_cli):
        """capture --annotate with --scrollback fails validation."""
        result = term_cli("capture", "-s", session, "-a", "-n", "50")
        assert not result.ok
        assert result.returncode == 2
        assert "annotate" in result.stderr.lower() or "combined" in result.stderr.lower()

    def test_capture_annotate_with_tail(self, session, term_cli):
        """capture --annotate --tail shows only last N lines with annotations."""

        # Fill screen with numbered lines so we know what to expect
        for i in range(1, 15):
            term_cli("run", "-s", session, f"echo line{i}", "-w")
        # Add a highlight near the bottom
        term_cli("run", "-s", session,
                 r"printf '\033[42m  TAIL_HIGHLIGHT  \033[0m\n'", "-w")

        result = term_cli("capture", "-s", session, "-a", "--tail", "5", "--line-numbers")
        assert result.ok

        stdout = result.stdout
        lines = stdout.strip().split("\n")

        # Should have Annotations: section
        assert "Annotations:" in stdout

        # Find the numbered content lines (before Annotations:)
        content_lines: list[str] = []
        for line in lines:
            if "Annotations:" in line:
                break
            stripped = line.strip()
            if stripped and "│" in stripped:
                content_lines.append(stripped)

        # Should have at most 5 content lines
        assert len(content_lines) <= 5, (
            f"Expected at most 5 content lines, got {len(content_lines)}: {content_lines}"
        )

        # Line numbers should be high (not starting from 1) since we're
        # showing the tail of a screen that has many lines
        first_num_match = re.match(r"(\d+)│", content_lines[0])
        assert first_num_match is not None
        first_num = int(first_num_match.group(1))
        assert first_num > 5, (
            f"First line number should be > 5 (tail of screen), got {first_num}"
        )

        # The highlight should be visible in the tail
        assert "TAIL_HIGHLIGHT" in stdout

        # Cursor position should always be present
        assert "Cursor:" in stdout

    def test_capture_annotate_line_number_overflow(self, session_factory, term_cli) -> None:
        """Line numbers >999 overflow the 3-digit field naturally."""

        # Create a session tall enough that row 1000+ exists
        session = session_factory(cols=80, rows=1002)
        # Put a highlight on the last visible row (row 1002)
        # First fill to push cursor near bottom, then print highlight
        term_cli("run", "-s", session,
                 r"for i in $(seq 1 1000); do echo line$i; done", "-w", "-t", "30")
        term_cli("run", "-s", session,
                 r"printf '\033[42m  OVERFLOW_MARK  \033[0m\n'", "-w")

        result = term_cli("capture", "-s", session, "-a", "--line-numbers")
        assert result.ok
        stdout = result.stdout

        # Verify 3-digit and 4-digit line numbers both use │ delimiter
        assert re.search(r"^\s*1│ ", stdout, re.MULTILINE), "Row 1 should be formatted"
        # The 4-digit row numbers should still have │
        assert re.search(r"\d{4}│ ", stdout), "4-digit row numbers should overflow naturally"
        # The highlight should be detected
        assert "OVERFLOW_MARK" in stdout

    def test_capture_annotate_tail_excludes_early_annotations(
        self, session, term_cli
    ) -> None:
        """--tail filters annotations to the visible window only."""
        # Put a highlight early
        term_cli("run", "-s", session,
                 r"printf '\033[42m  EARLY_MARK  \033[0m\n'", "-w")
        # Push it off the tail window with plain lines
        for i in range(20):
            term_cli("run", "-s", session, f"echo plain{i}", "-w")

        result = term_cli("capture", "-s", session, "-a", "--tail", "3")
        assert result.ok
        stdout = result.stdout

        # EARLY_MARK should NOT appear anywhere (not in lines, not in annotations)
        assert "EARLY_MARK" not in stdout
        # Metadata should still be present
        assert "Annotations:" in stdout
        assert "Cursor:" in stdout

    def test_capture_annotate_nonexistent_session(self, term_cli):
        """capture --annotate on nonexistent session fails."""
        result = term_cli("capture", "-s", "nonexistent_xyz", "-a")
        assert not result.ok
        assert result.returncode == 2


class TestSendStdin:
    """Tests for the 'send-stdin' command."""

    def test_send_stdin_single_line(self, session, term_cli, tmux_socket):
        """send-stdin sends content from stdin to session."""

        # Use subprocess directly to pipe content
        proc = subprocess.run(
            [TERM_CLI, "-L", tmux_socket, "send-stdin", "-s", session],
            input="hello from stdin\n",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "Sent" in proc.stdout
        assert "chars" in proc.stdout
        
        # Verify content was sent (use joined wraps — text is at the prompt)
        assert wait_for_content(term_cli, session, "hello from stdin"), "stdin content not found"
        assert "hello from stdin" in capture_content(term_cli, session)

    def test_send_stdin_multiline(self, session, term_cli, tmux_socket):
        """send-stdin sends multiline content correctly."""

        content = "line1\nline2\nline3\n"
        proc = subprocess.run(
            [TERM_CLI, "-L", tmux_socket, "send-stdin", "-s", session],
            input=content,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "3 lines" in proc.stdout
        
        # Verify all lines were sent
        assert wait_for_content(term_cli, session, "line3"), "multiline content not found"
        result = term_cli("capture", "-s", session)
        assert "line1" in result.stdout
        assert "line2" in result.stdout
        assert "line3" in result.stdout

    def test_send_stdin_to_cat(self, session, term_cli, tmux_socket):
        """send-stdin can send content to cat for echoing."""

        # Start cat waiting for input
        term_cli("run", "-s", session, "cat")
        # Wait for cat to start
        def check_cat_running():
            result = term_cli("status", "-s", session)
            return "cat" in result.stdout
        assert retry_until(check_cat_running, timeout=15.0), "cat never started"
        
        # Send content via stdin
        proc = subprocess.run(
            [TERM_CLI, "-L", tmux_socket, "send-stdin", "-s", session],
            input="hello\n",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        
        # Wait for cat to echo
        assert wait_for_content(term_cli, session, "hello"), "cat didn't echo content"
        result = term_cli("capture", "-s", session)
        # The text should appear twice: once as input, once as cat output
        assert "hello" in result.stdout
        
        # Clean up - send Ctrl+D to exit cat
        term_cli("send-key", "-s", session, "C-d")

    def test_send_stdin_nonexistent_session(self, term_cli, tmux_socket):
        """send-stdin on non-existent session raises error."""

        proc = subprocess.run(
            [TERM_CLI, "-L", tmux_socket, "send-stdin", "-s", "nonexistent_xyz"],
            input="test\n",
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
        assert "does not exist" in proc.stderr

    def test_send_stdin_no_input(self, term_cli, session, tmux_socket):
        """send-stdin with no stdin input returns error."""

        # Run without piping anything (stdin is tty)
        # This test needs a different approach since subprocess always provides stdin
        proc = subprocess.run(
            [TERM_CLI, "-L", tmux_socket, "send-stdin", "-s", session],
            input="",  # Empty input
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2  # EXIT_INPUT_ERROR
        assert "Empty input" in proc.stderr


class TestAnnotationUnit:
    """Unit tests for internal annotation functions (_parse_raw_screen, _annotate_raw)."""

    @pytest.fixture(scope="class")
    def annotation_module(self) -> Any:
        """Import annotation functions from term-cli executable."""
        from importlib.machinery import SourceFileLoader

        term_cli_path = Path(__file__).parent.parent / "term-cli"
        loader = SourceFileLoader("term_cli_module", str(term_cli_path))
        spec = importlib.util.spec_from_loader("term_cli_module", loader)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Failed to load module spec for {term_cli_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    @pytest.fixture(scope="class")
    def parse_raw_screen(self, annotation_module: Any) -> Callable[..., Any]:
        """Get _parse_raw_screen function."""
        return annotation_module._parse_raw_screen  # type: ignore[no-any-return]

    @pytest.fixture(scope="class")
    def annotate_raw(self, annotation_module: Any) -> Callable[..., list[tuple[int, str, str]]]:
        """Get _annotate_raw function."""
        return annotation_module._annotate_raw  # type: ignore[no-any-return]

    @pytest.fixture(scope="class")
    def color_256_to_rgb(
        self, annotation_module: Any,
    ) -> Callable[[int], tuple[int, int, int] | None]:
        """Get _color_256_to_rgb function."""
        return annotation_module._color_256_to_rgb  # type: ignore[no-any-return]

    # ==================== _parse_raw_screen ====================

    def test_parse_plain_text(self, parse_raw_screen: Callable[..., Any]) -> None:
        """Plain text produces segments with default bg color."""
        rows = parse_raw_screen("hello world\n")
        assert len(rows) >= 1
        # First row should have at least one segment with the text
        text = "".join(seg[0] for seg in rows[0])
        assert "hello world" in text
        # seg is (text, fg_rgb, bg_rgb, bold) — bg should be default black
        for seg in rows[0]:
            assert seg[2] == (0, 0, 0)  # bg_rgb is default black

    def test_parse_colored_bg(self, parse_raw_screen: Callable[..., Any]) -> None:
        """SGR background color is parsed correctly."""
        # \033[42m = green background
        raw = "\033[42mGREEN BG\033[0m normal\n"
        rows = parse_raw_screen(raw)
        assert len(rows) >= 1
        # Find the segment with "GREEN BG"
        green_seg = None
        for seg in rows[0]:
            if "GREEN BG" in seg[0]:
                green_seg = seg
                break
        assert green_seg is not None, f"No segment with 'GREEN BG' found in {rows[0]}"
        # Green basic color: index 2 → (0, 128, 0) or similar
        # seg is (text, fg_rgb, bg_rgb, bold)
        assert green_seg[2] != (0, 0, 0)  # has a non-default bg color
        assert green_seg[2][1] > 0  # green channel > 0

    def test_color_256_cube_mapping_matches_xterm(
        self, color_256_to_rgb: Callable[[int], tuple[int, int, int] | None],
    ) -> None:
        """xterm 256-color cube indices map to correct RGB values."""
        assert color_256_to_rgb(16) == (0, 0, 0)
        assert color_256_to_rgb(17) == (0, 0, 95)
        assert color_256_to_rgb(21) == (0, 0, 255)
        assert color_256_to_rgb(52) == (95, 0, 0)
        assert color_256_to_rgb(88) == (135, 0, 0)
        assert color_256_to_rgb(160) == (215, 0, 0)
        assert color_256_to_rgb(196) == (255, 0, 0)
        assert color_256_to_rgb(231) == (255, 255, 255)

    def test_annotate_exact_named_rgb_uses_named_label(
        self, annotate_raw: Callable[..., list[tuple[int, str, str]]],
    ) -> None:
        """Exact named RGB backgrounds are labeled with color names."""
        lines = [f"normal line {i}" for i in range(20)]
        # Exact bright-red from _BRIGHT_COLORS.
        lines[10] = "\033[48;2;255;85;85m  RED_NAMED  \033[0m"
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        row10 = [(r, t, l) for r, t, l in annotations if r == 10 and "RED_NAMED" in t]
        assert row10, f"Expected RED_NAMED annotation on row 10, got: {annotations}"
        assert any(label == "bg:bright-red" for _r, _t, label in row10), (
            f"Expected bg:bright-red label for RED_NAMED, got: {row10}"
        )

    def test_annotate_256_color_uses_rgb_label_when_not_named(
        self, annotate_raw: Callable[..., list[tuple[int, str, str]]],
    ) -> None:
        """256-color backgrounds with no named match use bg:rgb(...) labels."""
        lines = [f"normal line {i}" for i in range(20)]
        # 17 maps to RGB(0,0,95), which is not in the basic/bright named sets.
        lines[10] = "\033[48;5;17m  BLUE_17  \033[0m"
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        row10 = [(r, t, l) for r, t, l in annotations if r == 10 and "BLUE_17" in t]
        assert row10, f"Expected BLUE_17 annotation on row 10, got: {annotations}"
        assert any(label == "bg:rgb(0,0,95)" for _r, _t, label in row10), (
            f"Expected bg:rgb(0,0,95) label for BLUE_17, got: {row10}"
        )

    def test_parse_reverse_video(self, parse_raw_screen: Callable[..., Any]) -> None:
        """Reverse video resolves to a concrete bg color."""
        raw = "\033[7mREVERSED\033[0m\n"
        rows = parse_raw_screen(raw)
        assert len(rows) >= 1
        rev_seg = None
        for seg in rows[0]:
            if "REVERSED" in seg[0]:
                rev_seg = seg
                break
        assert rev_seg is not None
        # seg is (text, fg_rgb, bg_rgb, bold) — reverse is resolved into bg_rgb
        assert rev_seg[2] != (0, 0, 0)  # has a non-default bg color

    def test_parse_state_carries_across_lines(self, parse_raw_screen: Callable[..., Any]) -> None:
        """ANSI state carries across line boundaries (critical bug fix)."""
        # Set bg on line 1, text continues on line 2 without resetting
        raw = "\033[41mRED LINE1\nRED LINE2\033[0m\n"
        rows = parse_raw_screen(raw)
        assert len(rows) >= 2
        # Line 2 should still have red bg
        line2_text = "".join(seg[0] for seg in rows[1])
        assert "RED LINE2" in line2_text
        # Find the segment with "RED LINE2"
        red_seg = None
        for seg in rows[1]:
            if "RED LINE2" in seg[0]:
                red_seg = seg
                break
        assert red_seg is not None
        assert red_seg[2] != (0, 0, 0)  # has a bg color (red)

    def test_parse_256_color_bg(self, parse_raw_screen: Callable[..., Any]) -> None:
        """256-color background SGR is parsed."""
        # \033[48;5;196m = 256-color index 196 (red)
        raw = "\033[48;5;196mINDEXED\033[0m\n"
        rows = parse_raw_screen(raw)
        assert len(rows) >= 1
        idx_seg = None
        for seg in rows[0]:
            if "INDEXED" in seg[0]:
                idx_seg = seg
                break
        assert idx_seg is not None
        assert idx_seg[2] != (0, 0, 0)  # has a bg color

    def test_parse_truecolor_bg(self, parse_raw_screen: Callable[..., Any]) -> None:
        """24-bit truecolor background is parsed."""
        # \033[48;2;100;150;200m = truecolor bg
        raw = "\033[48;2;100;150;200mTRUECOLOR\033[0m\n"
        rows = parse_raw_screen(raw)
        assert len(rows) >= 1
        tc_seg = None
        for seg in rows[0]:
            if "TRUECOLOR" in seg[0]:
                tc_seg = seg
                break
        assert tc_seg is not None
        assert tc_seg[2] == (100, 150, 200)

    def test_parse_reset_clears_state(self, parse_raw_screen: Callable[..., Any]) -> None:
        """SGR 0 reset clears all state."""
        raw = "\033[41;7;1mSTYLED\033[0mPLAIN\n"
        rows = parse_raw_screen(raw)
        assert len(rows) >= 1
        plain_seg = None
        for seg in rows[0]:
            if "PLAIN" in seg[0]:
                plain_seg = seg
                break
        assert plain_seg is not None
        # After reset: default bg, not bold — seg is (text, fg_rgb, bg_rgb, bold)
        assert plain_seg[2] == (0, 0, 0)  # default bg (black)
        assert plain_seg[3] is False  # not bold

    def test_parse_empty_input(self, parse_raw_screen: Callable[..., Any]) -> None:
        """Empty input returns empty or minimal result."""
        rows = parse_raw_screen("")
        # Should not crash; either empty list or list with one empty row
        assert isinstance(rows, list)

    # ==================== _annotate_raw ====================

    def test_annotate_plain_text_no_annotations(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Plain text with no color produces no annotations."""
        raw = "hello world\nfoo bar\nbaz\n"
        annotations = annotate_raw(raw)
        assert annotations == []

    def test_annotate_reverse_video_detected(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Reverse video text is detected as a highlight."""
        # Build a screen: mostly plain lines, one line with reverse video
        lines = []
        for i in range(20):
            lines.append(f"plain line {i}")
        # Replace line 10 with a reverse-video highlight
        lines[10] = f"\033[7m  SELECTED ITEM  \033[0m"
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        assert len(annotations) > 0
        # Should find annotation on row 10 (0-based)
        rows = [a[0] for a in annotations]
        assert 10 in rows
        # Should contain the text
        texts = [a[1] for a in annotations]
        assert any("SELECTED ITEM" in t for t in texts)

    def test_annotate_colored_bg_detected(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Colored background text is detected as a highlight."""
        lines = []
        for i in range(20):
            lines.append(f"normal line {i}")
        # Line 5: green background
        lines[5] = f"\033[42m  ACTIVE TAB  \033[0m"
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        assert len(annotations) > 0
        rows = [a[0] for a in annotations]
        assert 5 in rows  # 0-based
        texts = [a[1] for a in annotations]
        assert any("ACTIVE TAB" in t for t in texts)

    def test_annotate_structural_bg_ignored(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Large structural background regions are not annotated.

        A bg color covering many rows (like a TUI panel background) should be
        classified as structural and ignored.
        """
        # Create a "TUI" where blue bg covers most of the screen
        lines = []
        for i in range(24):
            lines.append(f"\033[44m{'content ' + str(i):80s}\033[0m")
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        # Large uniform bg covering the entire screen is structural → no annotations
        assert annotations == []

    def test_annotate_highlight_on_structural_bg(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """A highlight (reverse or different bg) on a structural bg is detected."""
        lines = []
        # Blue bg structural panel
        for i in range(24):
            lines.append(f"\033[44m{'  item ' + str(i):80s}\033[0m")
        # Replace one line with reverse video (highlight on the blue panel)
        lines[10] = f"\033[44;7m{'> selected item':80s}\033[0m"
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        assert len(annotations) > 0
        rows = [a[0] for a in annotations]
        assert 10 in rows  # 0-based row for line index 10

    def test_annotate_empty_input(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Empty input produces no annotations."""
        assert annotate_raw("") == []

    def test_annotate_multiple_highlights(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Multiple highlights on different rows are all detected."""
        lines = []
        for i in range(20):
            lines.append(f"normal line {i}")
        lines[3] = "\033[42m  GREEN HIGHLIGHT  \033[0m"
        lines[15] = "\033[7m  REVERSE HIGHLIGHT  \033[0m"
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        rows = [a[0] for a in annotations]
        assert 3 in rows   # 0-based for line 3
        assert 15 in rows  # 0-based for line 15

    def test_annotate_signal_c_short_flanked_run(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Signal C detects a short default-bg run flanked by colored runs.

        Simulates a dialog box (reverse video) with a focused button rendered
        in normal video — the button is a high-frequency colour transition.
        """
        lines = []
        for i in range(20):
            lines.append(f"normal line {i:70d}")
        # Build a dialog-like row: reverse-bg | default-bg button | reverse-bg
        # The button text is short and flanked by longer reverse-video runs
        lines[10] = (
            "\033[7m" + " " * 20 +          # 20 chars reverse
            "\033[0m" + "[ OK ]" +           # 6 chars default (the button)
            "\033[7m" + " " * 20 +           # 20 chars reverse
            "\033[0m"
        )
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        # Should detect the button on row 10 (0-based)
        assert any(r == 10 and "OK" in t for r, t, _l in annotations), \
            f"Expected annotation with 'OK' on row 10, got: {annotations}"

    def test_annotate_signal_c_no_false_positive_uniform(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Signal C does not fire on uniform rows (no short flanked runs)."""
        lines = []
        for i in range(20):
            lines.append(f"plain text line {i}")
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        assert annotations == []

    def test_dedup_same_row_label_keeps_longest(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """When multiple signals report same (row, label), longest text wins."""
        # Build a screen where Signal B and Signal C both fire on the same row.
        # 20 rows of structural blue background (full-width), then a bar row
        # with alternating cyan/black runs.  Blue is structural (tall region);
        # cyan disrupts the blue column-dominants (Signal B) and also forms a
        # high-frequency bar (Signal C).  Signal C combines all labels →
        # longer text than Signal B's single element.
        blue = "\033[44m"
        cyan = "\033[46m"
        black = "\033[40m"
        reset = "\033[0m"
        lines = []
        for i in range(20):
            lines.append(f"{blue}{'normal line':80s}{reset}")
        # Bar row: 10 alternating runs (black number + cyan label) × 5
        bar = ""
        labels = ["Help", "Menu", "View", "Edit", "Copy"]
        for idx, label in enumerate(labels):
            bar += f"{black} {idx + 1}{cyan}{label:6s}"
        bar += reset
        lines[19] = bar
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        # Should have exactly one annotation for row 19 with bg:cyan
        cyan_annos = [(r, t, l) for r, t, l in annotations if r == 19 and "cyan" in l]
        assert len(cyan_annos) == 1, f"Expected 1 cyan annotation on row 19, got: {cyan_annos}"
        # The text should contain commas (Signal C's combined output)
        assert "," in cyan_annos[0][1], f"Expected comma-separated text, got: {cyan_annos[0][1]}"

    def test_dedup_different_labels_same_row_both_kept(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Two different bg labels on the same row are both preserved."""
        lines = []
        for i in range(20):
            lines.append(f"normal line {i}")
        # Put green and red highlights on the same row
        lines[10] = (
            "\033[42m  GREEN_ITEM  \033[0m"
            "    "
            "\033[41m  RED_ITEM  \033[0m"
        )
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        row10 = [(r, t, l) for r, t, l in annotations if r == 10]
        assert len(row10) >= 2, f"Expected >=2 annotations on row 10, got: {row10}"
        labels = {l for _, _, l in row10}
        assert "bg:green" in labels, f"Expected bg:green in {labels}"
        assert "bg:red" in labels, f"Expected bg:red in {labels}"

    def test_bar_detection_exactly_6_runs(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Bar detection triggers at exactly 6 alternating runs (minimum threshold)."""
        cyan = "\033[46m"
        black = "\033[40m"
        reset = "\033[0m"
        lines = []
        for i in range(20):
            lines.append(f"normal line {i}")
        # 6 alternating runs: cyan-black-cyan-black-cyan-black
        # Cyan runs: 10 chars with text; black runs: 2 chars (below flank minimum)
        lines[10] = (
            f"{cyan}{'Label1':10s}{black}  "
            f"{cyan}{'Label2':10s}{black}  "
            f"{cyan}{'Label3':10s}{black}  "
            f"{reset}"
        )
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        # Bar mode should trigger — cyan labels detected despite 2-wide black flanks
        row10 = [(r, t, l) for r, t, l in annotations if r == 10]
        assert any("Label1" in t for _, t, _ in row10), \
            f"Expected Label1 on row 10 (bar mode), got: {row10}"

    def test_bar_detection_5_runs_no_bar_mode(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """5 alternating runs is below bar threshold — narrow flanks cause rejection."""
        cyan = "\033[46m"
        black = "\033[40m"
        reset = "\033[0m"
        # Make cyan structural (widespread) so Signal A won't fire on it.
        # Then only Signal C could detect the cyan labels, but with 5 runs
        # bar mode won't activate and the 2-wide black flanks block it.
        lines = []
        for i in range(20):
            lines.append(f"{cyan}{'structural cyan row':80s}{reset}")
        # 5 alternating runs: cyan-black-cyan-black-cyan
        # Black runs are 2 chars wide (below flank minimum of 3)
        # Pad the last cyan segment to fill 80 cols so no trailing
        # black padding run is created (which would make 6 runs).
        lines[10] = (
            f"{cyan}{'LabelA':10s}{black}  "
            f"{cyan}{'LabelB':10s}{black}  "
            f"{cyan}{'LabelC':56s}"
            f"{reset}"
        )
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        # With cyan structural and only 5 runs (no bar mode), Signal C
        # should not produce annotations for this row because the 2-wide
        # black flanks fail the minimum flank width check.
        row10_cyan = [(r, t, l) for r, t, l in annotations
                      if r == 10 and "cyan" in l]
        assert len(row10_cyan) == 0, \
            f"Signal C should not fire with 5 runs and narrow flanks: {row10_cyan}"

    def test_bar_short_text_separators_included(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Bar-mode includes short text runs (hotkey numbers) alongside labels."""
        cyan = "\033[46m"
        black = "\033[40m"
        reset = "\033[0m"
        lines = []
        for i in range(20):
            lines.append(f"normal line {i}")
        # mc-style bar: black numbers (1-2 chars) + cyan labels (4+ chars)
        bar = ""
        for idx, label in enumerate(["Help", "Menu", "View"], 1):
            bar += f"{black} {idx}{cyan}{label:6s}"
        for idx, label in enumerate(["Edit", "Copy", "Quit"], 4):
            bar += f"{black} {idx}{cyan}{label:6s}"
        bar += reset
        lines[10] = bar
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        row10 = [(r, t, l) for r, t, l in annotations if r == 10]
        # Black numbers should be annotated in bar mode
        black_annos = [a for a in row10 if "black" in a[2]]
        assert len(black_annos) == 1, \
            f"Expected black annotation with hotkey numbers: {row10}"
        assert "1" in black_annos[0][1]
        # Cyan annotation should exist with the labels
        cyan_annos = [a for a in row10 if "cyan" in a[2]]
        assert len(cyan_annos) >= 1, f"Expected cyan annotation: {row10}"
        assert "Help" in cyan_annos[0][1]

    def test_single_vs_multi_segment_comma_formatting(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Single contiguous segment has no commas; disjoint segments are comma-separated."""
        # Screen 1: single contiguous green-bg span
        lines1 = [f"normal line {i}" for i in range(20)]
        lines1[5] = "\033[42m  Contiguous Text Here  \033[0m"
        raw1 = "\n".join(lines1) + "\n"
        annos1 = annotate_raw(raw1)
        row5 = [t for r, t, l in annos1 if r == 5 and "green" in l]
        assert len(row5) == 1
        assert "," not in row5[0], f"Single segment should not have commas: {row5[0]}"

        # Screen 2: two disjoint green-bg spans separated by default bg
        lines2 = [f"normal line {i}" for i in range(20)]
        lines2[5] = "\033[42m  First  \033[0m          \033[42m  Second  \033[0m"
        raw2 = "\n".join(lines2) + "\n"
        annos2 = annotate_raw(raw2)
        row5b = [t for r, t, l in annos2 if r == 5 and "green" in l]
        assert len(row5b) == 1
        assert "," in row5b[0], f"Disjoint segments should be comma-separated: {row5b[0]}"
        assert "First" in row5b[0] and "Second" in row5b[0]

    def test_annotate_long_text_no_truncation(self, annotate_raw: Callable[..., list[tuple[int, str, str]]]) -> None:
        """Annotation text is never truncated, even for very wide terminals."""
        # Build a 200-column screen with a full-width green highlight
        long_text = "A" * 200
        lines = []
        for i in range(20):
            lines.append(" " * 200)
        lines[10] = f"\033[42m{long_text}\033[0m"
        raw = "\n".join(lines) + "\n"
        annotations = annotate_raw(raw)
        row10 = [(r, t, l) for r, t, l in annotations if r == 10]
        assert len(row10) >= 1, f"Expected annotation on row 10, got: {annotations}"
        # Full 200 chars should be present, not truncated
        assert len(row10[0][1]) == 200, \
            f"Expected 200 chars, got {len(row10[0][1])}: {row10[0][1]!r}"
