"""
Tests for I/O commands: run, send-text, send-key, send-stdin, capture.
"""

from __future__ import annotations

import time

from conftest import RunResult, capture_content, wait_for_content, retry_until


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
        
        # Verify content was sent (use joined wraps — text is at the prompt)
        assert wait_for_content(term_cli, session, "hello from stdin"), "stdin content not found"
        assert "hello from stdin" in capture_content(term_cli, session)

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
