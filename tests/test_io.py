"""
Tests for I/O commands: run, send-text, send-key, send-stdin, capture.
"""

from __future__ import annotations

import time

from conftest import RunResult, wait_for_content, retry_until


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


class TestSendText:
    """Tests for the 'send-text' command."""

    def test_send_text_sends_literal(self, session, term_cli):
        """send-text sends literal text."""
        term_cli("send-text", "-s", session, "echo hello")
        result = term_cli("capture", "-s", session)
        # Text should appear but not execute (no Enter)
        assert "echo hello" in result.stdout

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
        assert retry_until(check_sleep_running, timeout=3.0), "sleep never started"
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
        assert retry_until(check_cat_running, timeout=3.0), "cat never started"
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
        result = term_cli("capture", "-s", session)
        # Up arrow should recall "echo first"
        assert "echo first" in result.stdout

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
        result = term_cli("capture", "-s", session)
        # Tab completion should complete to the full filename
        assert "tabtest_unique_file.txt" in result.stdout, \
            f"Tab completion should have completed the filename: {result.stdout}"
        # Clean up - send Ctrl+C to cancel
        term_cli("send-key", "-s", session, "C-c")

    def test_send_key_backspace(self, session, term_cli):
        """send-key BSpace sends backspace and deletes characters."""
        # Use a unique string to avoid matching prompt contents
        term_cli("send-text", "-s", session, "XYZZY")
        assert wait_for_content(term_cli, session, "XYZZY"), "Text wasn't sent"
        term_cli("send-key", "-s", session, "BSpace")
        term_cli("send-key", "-s", session, "BSpace")
        # Wait for backspace to take effect - should see XYZ but not XYZZY
        def check_backspace_worked():
            result = term_cli("capture", "-s", session)
            return "XYZ" in result.stdout and "XYZZY" not in result.stdout
        assert retry_until(check_backspace_worked, timeout=3.0), "Backspace didn't delete characters"
        result = term_cli("capture", "-s", session)
        # Should have "XYZ" not "XYZZY" - backspace deleted 2 chars
        assert "XYZ" in result.stdout
        # The full "XYZZY" should not appear anywhere (backspace deleted "ZY")
        assert "XYZZY" not in result.stdout, \
            f"Backspace should have deleted characters. Output: {result.stdout}"

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
        capture = term_cli("capture", "-s", session)
        assert "NotARealKey" in capture.stdout


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
        """capture --lines includes scrollback history."""
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

    def test_capture_lines_zero(self, session, term_cli):
        """capture --lines 0 captures from current position (no scrollback)."""
        term_cli("run", "-s", session, "echo test", "-w")
        result = term_cli("capture", "-s", session, "-n", "0")
        assert result.ok
        # With -n 0, we still see current content, just no scrollback
        # The prompt and recent output should be visible
        assert len(result.stdout) > 0

    def test_capture_lines_large_number(self, session, term_cli):
        """capture --lines with large number works."""
        term_cli("run", "-s", session, "echo test", "-w")
        result = term_cli("capture", "-s", session, "-n", "10000")
        assert result.ok
        assert "test" in result.stdout

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
        """capture --raw --lines includes ANSI codes in scrollback."""
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


class TestSendStdin:
    """Tests for the 'send-stdin' command."""

    def test_send_stdin_single_line(self, session, term_cli, tmux_socket):
        """send-stdin sends content from stdin to session."""
        import subprocess
        from conftest import TERM_CLI
        
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
        
        # Verify content was sent
        assert wait_for_content(term_cli, session, "hello from stdin"), "stdin content not found"
        result = term_cli("capture", "-s", session)
        assert "hello from stdin" in result.stdout

    def test_send_stdin_multiline(self, session, term_cli, tmux_socket):
        """send-stdin sends multiline content correctly."""
        import subprocess
        from conftest import TERM_CLI
        
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
        import subprocess
        from conftest import TERM_CLI
        
        # Start cat waiting for input
        term_cli("run", "-s", session, "cat")
        # Wait for cat to start
        def check_cat_running():
            result = term_cli("status", "-s", session)
            return "cat" in result.stdout
        assert retry_until(check_cat_running, timeout=3.0), "cat never started"
        
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
        import subprocess
        from conftest import TERM_CLI
        
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
        import subprocess
        from conftest import TERM_CLI
        
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
