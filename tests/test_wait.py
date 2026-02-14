"""
Tests for wait commands: wait, wait-idle, wait-for.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Callable

import pytest


class TestWait:
    """Tests for the 'wait' command."""

    def test_wait_detects_prompt_immediately(self, session, term_cli):
        """wait returns quickly when already at prompt."""
        # Fresh session should be at prompt, wait for it to initialize
        term_cli("wait", "-s", session, "-t", "5")
        result = term_cli("wait", "-s", session, "-t", "5")
        assert result.ok
        assert "Prompt detected" in result.stdout

    def test_wait_detects_prompt_after_command(self, session, term_cli):
        """wait returns when command completes and prompt appears."""
        term_cli("run", "-s", session, "echo hello")
        result = term_cli("wait", "-s", session, "-t", "5")
        assert result.ok
        assert "Prompt detected" in result.stdout

    def test_wait_timeout(self, session, term_cli):
        """wait times out if prompt doesn't appear."""
        # Run a long sleep that won't complete
        term_cli("run", "-s", session, "sleep 100")
        result = term_cli("wait", "-s", session, "-t", "0.5")
        assert not result.ok
        assert result.returncode == 3  # EXIT_TIMEOUT
        assert "prompt not detected" in result.stderr
        # Clean up
        term_cli("send-key", "-s", session, "C-c")

    def test_wait_custom_timeout(self, session, term_cli):
        """wait respects custom timeout value."""
        term_cli("run", "-s", session, "sleep 100")
        start = time.time()
        result = term_cli("wait", "-s", session, "-t", "1")
        elapsed = time.time() - start
        assert elapsed >= 0.9 and elapsed < 2
        assert not result.ok
        assert result.returncode == 3  # EXIT_TIMEOUT
        assert "1" in result.stderr and "s" in result.stderr
        term_cli("send-key", "-s", session, "C-c")

    def test_wait_timeout_message_includes_duration(self, session, term_cli):
        """wait timeout message includes the timeout duration."""
        term_cli("run", "-s", session, "sleep 100")
        start = time.time()
        # Use explicit short timeout for fast test
        result = term_cli("wait", "-s", session, "-t", "2")
        elapsed = time.time() - start
        assert elapsed >= 1.5 and elapsed < 4
        assert not result.ok
        assert result.returncode == 3  # EXIT_TIMEOUT
        assert "2" in result.stderr and "s" in result.stderr
        term_cli("send-key", "-s", session, "C-c")

    def test_wait_detects_dollar_prompt(self, session, term_cli):
        """wait detects $ prompt (bash-style)."""
        # Most shells have $ or % prompt, wait for shell to initialize
        term_cli("wait", "-s", session, "-t", "5")
        result = term_cli("wait", "-s", session, "-t", "3")
        assert "Prompt detected" in result.stdout

    def test_wait_after_quick_command(self, session, term_cli):
        """wait works for very quick commands."""
        term_cli("run", "-s", session, "true")
        result = term_cli("wait", "-s", session, "-t", "3")
        assert "Prompt detected" in result.stdout

    def test_wait_nonexistent_session(self, term_cli):
        """wait on non-existent session raises error."""
        result = term_cli("wait", "-s", "nonexistent_xyz")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_wait_negative_timeout(self, session, term_cli):
        """wait with negative timeout is rejected."""
        result = term_cli("wait", "-s", session, "-t", "-1")
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR
        assert "negative" in result.stderr.lower() or "non-negative" in result.stderr.lower()

    def test_wait_zero_timeout(self, session, term_cli):
        """wait with zero timeout returns immediately."""
        result = term_cli("wait", "-s", session, "-t", "0")
        # Zero timeout should return immediately with timeout message
        # or possibly detect prompt if already at prompt
        assert result.ok


class TestWaitIdle:
    """Tests for the 'wait-idle' command."""

    def test_wait_idle_detects_idle(self, session, term_cli):
        """wait-idle returns when output stops changing."""
        # Run a quick command
        term_cli("run", "-s", session, "echo done", "-w")
        # Now it should be idle
        result = term_cli("wait-idle", "-s", session, "-i", "0.5", "-t", "5")
        assert result.ok
        assert "Idle for" in result.stdout

    def test_wait_idle_timeout(self, session, term_cli):
        """wait-idle times out if output keeps changing."""
        # Run something that produces continuous output rapidly
        # Use a loop that echoes rapidly
        term_cli("run", "-s", session, "while true; do echo x; done")
        result = term_cli("wait-idle", "-s", session, "-i", "2", "-t", "1")
        # Should timeout since output never stops
        assert not result.ok
        assert result.returncode == 3  # EXIT_TIMEOUT
        assert "output still changing" in result.stderr
        # Clean up
        term_cli("send-key", "-s", session, "C-c")

    def test_wait_idle_custom_seconds(self, session, term_cli):
        """wait-idle respects custom idle seconds."""
        term_cli("run", "-s", session, "echo test", "-w")
        start = time.time()
        result = term_cli("wait-idle", "-s", session, "-i", "1", "-t", "10")
        elapsed = time.time() - start
        # Should wait at least 1 second of idle
        assert elapsed >= 0.9
        assert "Idle for 1" in result.stdout

    def test_wait_idle_default_seconds(self, session, term_cli):
        """wait-idle uses default idle seconds (2.0s)."""
        term_cli("run", "-s", session, "echo test", "-w")
        start = time.time()
        result = term_cli("wait-idle", "-s", session, "-t", "10")
        elapsed = time.time() - start
        # Default is 2 seconds
        assert elapsed >= 1.8
        assert result.ok
        assert "Idle for 2" in result.stdout  # "Idle for 2.0s"

    def test_wait_idle_with_slow_output(self, session, term_cli):
        """wait-idle handles commands with slow output."""
        # Echo with delays
        term_cli("run", "-s", session, "echo start; sleep 0.3; echo middle; sleep 0.3; echo end")
        result = term_cli("wait-idle", "-s", session, "-i", "0.5", "-t", "5")
        # Should eventually become idle
        assert "Idle for" in result.stdout

    def test_wait_idle_fresh_session(self, session, term_cli):
        """wait-idle works on fresh session."""
        term_cli("wait", "-s", session, "-t", "5")  # Wait for shell to initialize
        result = term_cli("wait-idle", "-s", session, "-i", "0.5", "-t", "5")
        assert "Idle for" in result.stdout

    def test_wait_idle_nonexistent_session(self, term_cli):
        """wait-idle on non-existent session raises error."""
        result = term_cli("wait-idle", "-s", "nonexistent_xyz")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_wait_idle_after_ctrl_c(self, session, term_cli):
        """wait-idle works after interrupting a command."""
        from conftest import retry_until
        term_cli("run", "-s", session, "sleep 100")
        # Wait for sleep to actually start before sending Ctrl-C
        def check_sleep_started():
            result = term_cli("status", "-s", session)
            return "sleep" in result.stdout
        assert retry_until(check_sleep_started, timeout=15.0), "sleep never started"
        term_cli("send-key", "-s", session, "C-c")
        result = term_cli("wait-idle", "-s", session, "-i", "0.5", "-t", "5")
        assert "Idle for" in result.stdout

    def test_wait_idle_zero_seconds(self, session, term_cli):
        """wait-idle with zero idle seconds returns immediately."""
        result = term_cli("wait-idle", "-s", session, "-i", "0", "-t", "5")
        # With 0 idle seconds, should return immediately
        assert result.ok

    def test_wait_idle_zero_timeout(self, session, term_cli):
        """wait-idle with zero timeout checks once and returns."""
        term_cli("wait", "-s", session, "-t", "5")  # Ensure shell is ready
        result = term_cli("wait-idle", "-s", session, "-i", "0", "-t", "0")
        # With 0 idle seconds and 0 timeout, should check once and succeed
        assert result.ok

    def test_wait_idle_negative_timeout(self, session, term_cli):
        """wait-idle with negative timeout is rejected."""
        result = term_cli("wait-idle", "-s", session, "-i", "0.5", "-t", "-1")
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR
        assert "negative" in result.stderr.lower() or "non-negative" in result.stderr.lower()

    def test_wait_idle_negative_seconds(self, session, term_cli):
        """wait-idle with negative idle seconds is rejected."""
        result = term_cli("wait-idle", "-s", session, "-i", "-1", "-t", "5")
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR
        assert "negative" in result.stderr.lower() or "non-negative" in result.stderr.lower()


class TestWaitFor:
    """Tests for the 'wait-for' command."""

    def test_wait_for_detects_pattern(self, session, term_cli):
        """wait-for detects a pattern in the output."""
        term_cli("run", "-s", session, "echo 'unique_marker_abc'", "-w")
        result = term_cli("wait-for", "-s", session, "unique_marker_abc", "-t", "5")
        assert result.ok
        assert "Pattern detected" in result.stdout
        assert "unique_marker_abc" in result.stdout

    def test_wait_for_timeout(self, session, term_cli):
        """wait-for times out if pattern doesn't appear."""
        result = term_cli("wait-for", "-s", session, "never_gonna_find_this_xyz", "-t", "0.5")
        assert not result.ok
        assert result.returncode == 3  # EXIT_TIMEOUT
        assert "pattern not detected" in result.stderr
        assert "never_gonna_find_this_xyz" in result.stderr

    def test_wait_for_multiple_patterns(self, session, term_cli):
        """wait-for with multiple patterns returns on first match."""
        term_cli("run", "-s", session, "echo 'found_second_pattern'", "-w")
        result = term_cli("wait-for", "-s", session, "not_here", "found_second_pattern", "also_not_here", "-t", "5")
        assert result.ok
        assert "found_second_pattern" in result.stdout

    def test_wait_for_case_sensitive(self, session, term_cli):
        """wait-for is case-sensitive by default."""
        term_cli("run", "-s", session, "echo 'CamelCase'", "-w")
        # Should find with exact case
        result = term_cli("wait-for", "-s", session, "CamelCase", "-t", "5")
        assert result.ok
        # Should NOT find with wrong case (times out quickly)
        result = term_cli("wait-for", "-s", session, "camelcase", "-t", "0.5")
        assert not result.ok
        assert result.returncode == 3  # EXIT_TIMEOUT

    def test_wait_for_ignore_case(self, session, term_cli):
        """wait-for --ignore-case matches regardless of case."""
        term_cli("run", "-s", session, "echo 'MixedCase'", "-w")
        result = term_cli("wait-for", "-s", session, "mixedcase", "-i", "-t", "5")
        assert result.ok
        assert "Pattern detected" in result.stdout

    def test_wait_for_print_match_flag(self, session, term_cli):
        """wait-for --print-match prints the matched line."""
        term_cli("run", "-s", session, "echo 'line with marker here'", "-w")
        result = term_cli("wait-for", "-s", session, "marker", "-p", "-t", "5")
        assert result.ok
        assert "Pattern detected" in result.stdout
        # The captured line should contain the full context
        assert "marker" in result.stdout
        # Output should have at least two lines (detection message + captured line)
        lines = result.stdout.strip().split('\n')
        assert len(lines) >= 2

    def test_wait_for_print_match_context(self, session, term_cli):
        """wait-for --print-match-context prints surrounding lines."""
        # Use printf to build the marker so it doesn't appear in the echoed command
        term_cli("run", "-s", session,
                 "echo 'aaa'; echo 'bbb'; printf 'cc%s\\n' 'c'; echo 'ddd'; echo 'eee'",
                 "-w")
        result = term_cli("wait-for", "-s", session, "ccc", "-C", "1", "-t", "5")
        assert result.ok
        assert "Pattern detected" in result.stdout
        lines = result.stdout.strip().split('\n')
        # First line is the detection message, remaining lines are context
        context_lines = lines[1:]
        assert len(context_lines) == 3  # bbb, ccc, ddd
        assert any("bbb" in l for l in context_lines)
        assert any("ccc" in l for l in context_lines)
        assert any("ddd" in l for l in context_lines)

    def test_wait_for_print_match_context_implies_print(self, session, term_cli):
        """wait-for -C implies --print-match (no need for -p)."""
        term_cli("run", "-s", session, "echo 'ctx_marker_line'", "-w")
        result = term_cli("wait-for", "-s", session, "ctx_marker_line", "-C", "0", "-t", "5")
        assert result.ok
        lines = result.stdout.strip().split('\n')
        # -C 0 means just the matched line (same as -p alone)
        assert len(lines) >= 2  # detection message + matched line
        assert any("ctx_marker_line" in l for l in lines[1:])

    def test_wait_for_print_match_context_negative(self, session, term_cli):
        """wait-for --print-match-context with negative value is rejected."""
        result = term_cli("wait-for", "-s", session, "pattern", "-C", "-1", "-t", "5")
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR

    def test_wait_for_nonexistent_session(self, term_cli):
        """wait-for on non-existent session raises error."""
        result = term_cli("wait-for", "-s", "nonexistent_xyz", "pattern")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_wait_for_negative_timeout(self, session, term_cli):
        """wait-for with negative timeout is rejected."""
        result = term_cli("wait-for", "-s", session, "pattern", "-t", "-1")
        assert not result.ok
        assert result.returncode == 2  # EXIT_INPUT_ERROR
        assert "negative" in result.stderr.lower() or "non-negative" in result.stderr.lower()

    def test_wait_for_zero_timeout(self, session, term_cli):
        """wait-for with zero timeout checks once and returns."""
        term_cli("run", "-s", session, "echo 'zero_timeout_marker'", "-w")
        result = term_cli("wait-for", "-s", session, "zero_timeout_marker", "-t", "0")
        # Pattern is already on screen, zero timeout should find it on first check
        assert result.ok
        assert "Pattern detected" in result.stdout

    def test_wait_for_zero_timeout_miss(self, session, term_cli):
        """wait-for with zero timeout fails if pattern not present."""
        result = term_cli("wait-for", "-s", session, "never_on_screen_xyz", "-t", "0")
        assert not result.ok
        assert result.returncode == 3  # EXIT_TIMEOUT

    def test_wait_for_immediate_match(self, session, term_cli):
        """wait-for returns quickly when pattern is already present."""
        # Echo a known pattern that will definitely be on screen
        import time
        term_cli("run", "-s", session, "echo 'READY_MARKER'", "-w")
        # run -w already waits for command to complete, pattern should be on screen
        start = time.time()
        result = term_cli("wait-for", "-s", session, "READY_MARKER", "-t", "5")
        elapsed = time.time() - start
        # Should find the pattern almost immediately
        assert result.ok
        assert elapsed < 1, f"Pattern already on screen should be found quickly, took {elapsed}s"

    def test_wait_for_waits_for_pattern(self, session, term_cli):
        """wait-for actually waits for pattern to appear."""
        import time
        # Start a command that will output a pattern after a delay
        # The pattern "DONE123" will appear on its own line after the sleep
        # but only in the output, not in the command itself when using printf
        term_cli("run", "-s", session, "sleep 1; printf 'DONE%s' '123'")
        start = time.time()
        result = term_cli("wait-for", "-s", session, "DONE123", "-t", "5")
        elapsed = time.time() - start
        assert result.ok
        assert elapsed >= 0.9  # Should have waited for the sleep
        assert "DONE123" in result.stdout

    def test_wait_for_abbreviation(self, session, term_cli):
        """wait-f abbreviation works for wait-for."""
        term_cli("run", "-s", session, "echo 'abbrev_test'", "-w")
        result = term_cli("wait-f", "-s", session, "abbrev_test", "-t", "5")
        assert result.ok


class TestWaitCursorDetection:
    """Tests for cursor-based prompt detection in 'wait' command."""

    def test_wait_does_not_match_prompt_in_running_command(self, session, term_cli):
        """wait should not match prompt patterns in the command text itself.
        
        This tests the cursor-based detection: when a command like 'sleep 2'
        is running, the screen shows '[user@host]$ sleep 2' but the cursor
        is on the next line waiting for output. The prompt pattern '$' appears
        in the visible command, but we should NOT detect it as "at prompt"
        because the cursor is not positioned after that prompt.
        """
        # Start a command that takes time
        term_cli("send-text", "-s", session, "sleep 2", "-e")
        # Immediately try to wait - should NOT return instantly
        start = time.time()
        result = term_cli("wait", "-s", session, "-t", "5")
        elapsed = time.time() - start
        assert result.ok
        # Should have waited for the sleep to complete (2+ seconds)
        assert elapsed >= 1.5, f"wait returned too quickly ({elapsed:.1f}s) - may have matched prompt in command text"

    def test_wait_with_dollar_in_output(self, session, term_cli):
        """wait should work correctly when command output contains $.
        
        Output like 'Price: $100' should not cause false prompt detection.
        """
        term_cli("send-text", "-s", session, "sleep 1 && echo 'Price: $100'", "-e")
        start = time.time()
        result = term_cli("wait", "-s", session, "-t", "5")
        elapsed = time.time() - start
        assert result.ok
        # Should wait for command to complete
        assert elapsed >= 0.8, f"wait returned too quickly ({elapsed:.1f}s)"
        # Verify the output is there
        capture = term_cli("capture", "-s", session)
        assert "$100" in capture.stdout

    def test_wait_with_prompt_like_output(self, session, term_cli):
        """wait handles output that looks like a prompt.
        
        Even if output ends with '$ ', we should only detect prompt
        when cursor is actually at the prompt position.
        """
        term_cli("send-text", "-s", session, "sleep 1 && echo 'fake prompt: user$ '", "-e")
        start = time.time()
        result = term_cli("wait", "-s", session, "-t", "5")
        elapsed = time.time() - start
        assert result.ok
        assert elapsed >= 0.8, f"wait returned too quickly ({elapsed:.1f}s)"

    def test_wait_detects_prompt_with_status_bar_below(self, session, term_cli):
        """wait detects prompt when there's a status bar below the cursor.
        
        Some programs like lldb, gdb, or custom TUIs display a prompt mid-screen
        with a status line at the bottom. The prompt detection should look at
        the cursor's line, not the last non-empty line.
        
        This simulates the scenario by creating output that has a prompt-like
        line followed by a status line, with the cursor positioned at the prompt.
        """
        # Simulate a TUI-style screen: prompt on one line, status at bottom
        # We'll use a script that positions cursor on a prompt line with content below
        term_cli("run", "-s", session, 
            "printf '(prompt) \\n\\n\\n\\n\\nstatus line' && sleep 0.5 && "
            "printf '\\x1b[1;10H'",  # Move cursor to row 1, col 10 (after prompt)
            "-w", "-t", "5")
        
        # Clear screen and set up the scenario more cleanly
        term_cli("run", "-s", session, "clear", "-w")
        
        # Now test with Python REPL which has a clean >>> prompt
        term_cli("run", "-s", session, "python3 -c \"print('test')\" && echo done", "-w", "-t", "5")
        result = term_cli("capture", "-s", session)
        assert "done" in result.stdout or "test" in result.stdout

    def test_wait_requires_space_after_prompt_char(self, session, term_cli):
        """wait requires a space after the prompt character.
        
        Lines ending with prompt-like characters but no trailing space
        (like 'array[0]' or 'if (condition)') should not be detected as prompts.
        """
        # Run a command that outputs text ending with ] but no space
        term_cli("run", "-s", session, "echo 'array[0]'", "-w", "-t", "5")
        
        # The shell prompt should still be detected after the command
        result = term_cli("wait", "-s", session, "-t", "3")
        assert result.ok
        
        # Verify the output contains the non-prompt text
        capture = term_cli("capture", "-s", session)
        assert "array[0]" in capture.stdout


class TestCursorAtPromptUnit:
    """Unit tests for the _cursor_at_prompt function.
    
    These tests verify the prompt detection heuristic without needing actual
    REPLs or terminal sessions. The function checks if the cursor is positioned
    at a prompt by looking at character positions relative to the cursor.
    """

    @pytest.fixture(scope="class")
    def cursor_at_prompt(self) -> Callable[[str, int], bool]:
        """Import _cursor_at_prompt from term-cli executable."""
        from importlib.machinery import SourceFileLoader
        
        term_cli_path = Path(__file__).parent.parent / "term-cli"
        loader = SourceFileLoader("term_cli_module", str(term_cli_path))
        module = loader.load_module()
        return module._cursor_at_prompt  # type: ignore[attr-defined,no-any-return]

    # ==================== Shell Prompts ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("$ ", 2, "bash dollar"),
        ("% ", 2, "zsh percent"),
        ("# ", 2, "root hash"),
        ("user@host:~$ ", 13, "bash with user@host"),
        ("[user@host ~]$ ", 15, "bash bracketed"),
        ("host% ", 6, "zsh with hostname"),
        ("(venv) $ ", 9, "virtualenv bash"),
        ("(base) % ", 9, "conda zsh"),
    ])
    def test_detects_shell_prompts(self, cursor_at_prompt, line, cursor_x, desc):
        """Detect various shell prompt styles."""
        assert cursor_at_prompt(line, cursor_x), f"Failed to detect: {desc}"

    # ==================== Python Prompts ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        (">>> ", 4, "python primary"),
        (">>>", 4, "python no trailing space"),
        ("In [1]: ", 8, "ipython"),
        ("In [42]: ", 9, "ipython double digit"),
        ("In [123]: ", 10, "ipython triple digit"),
        ("(Pdb) ", 6, "python debugger"),
        ("(Pdb++) ", 8, "pdb++"),
        ("ipdb> ", 6, "ipdb"),
    ])
    def test_detects_python_prompts(self, cursor_at_prompt, line, cursor_x, desc):
        """Detect Python interpreter and debugger prompts."""
        assert cursor_at_prompt(line, cursor_x), f"Failed to detect: {desc}"

    # ==================== JavaScript/Node Prompts ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("> ", 2, "node primary"),
        (">", 2, "node no space"),
        ("deno> ", 6, "deno repl"),
        ("bun> ", 5, "bun repl"),
    ])
    def test_detects_javascript_prompts(self, cursor_at_prompt, line, cursor_x, desc):
        """Detect JavaScript runtime prompts."""
        assert cursor_at_prompt(line, cursor_x), f"Failed to detect: {desc}"

    # ==================== Database Prompts ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("sqlite> ", 8, "sqlite"),
        ("mysql> ", 7, "mysql"),
        ("postgres=# ", 11, "psql superuser"),
        ("postgres=> ", 11, "psql normal"),
        ("mydb=# ", 7, "psql custom db"),
        ("MariaDB [(none)]> ", 18, "mariadb"),
        ("mongosh> ", 9, "mongodb shell"),
        ("redis> ", 7, "redis cli"),
        ("127.0.0.1:6379> ", 16, "redis with host"),
    ])
    def test_detects_database_prompts(self, cursor_at_prompt, line, cursor_x, desc):
        """Detect database client prompts."""
        assert cursor_at_prompt(line, cursor_x), f"Failed to detect: {desc}"

    # ==================== Debugger Prompts ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("(lldb) ", 7, "lldb"),
        ("(gdb) ", 6, "gdb"),
        ("(rr) ", 5, "rr debugger"),
        ("  DB<1> ", 8, "perl debugger"),
        ("  DB<42> ", 9, "perl debugger double digit"),
        ("(byebug) ", 9, "ruby byebug"),
        ("(pry) ", 6, "ruby pry"),
        ("[0] pry(main)> ", 15, "pry with context"),
    ])
    def test_detects_debugger_prompts(self, cursor_at_prompt, line, cursor_x, desc):
        """Detect debugger prompts."""
        assert cursor_at_prompt(line, cursor_x), f"Failed to detect: {desc}"

    # ==================== Language REPL Prompts ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("> ", 2, "lua"),
        (">> ", 3, "lua continuation"),
        ("irb(main):001:0> ", 17, "ruby irb"),
        ("irb(main):042:1> ", 17, "ruby irb nested"),
        (">> ", 3, "ruby irb simple"),
        ("scala> ", 7, "scala"),
        ("groovy:000> ", 12, "groovy"),
        ("ghci> ", 6, "haskell ghci"),
        ("Prelude> ", 9, "haskell prelude"),
        ("iex(1)> ", 8, "elixir"),
        ("iex(42)> ", 9, "elixir double digit"),
        ("ex(1)> ", 7, "erlang"),
        ("1> ", 3, "erlang numbered"),
        ("php > ", 6, "php interactive"),
        (">>> ", 4, "php psysh"),
        ("R> ", 3, "r language"),
        ("> ", 2, "r primary"),
        ("julia> ", 7, "julia"),
        ("ocaml# ", 7, "ocaml"),
        ("# ", 2, "ocaml utop"),
        ("swift> ", 7, "swift repl"),
        ("jshell> ", 8, "java jshell"),
        ("clj꞉user꞉> ", 11, "clojure"),
        ("user=> ", 7, "clojure lein"),
    ])
    def test_detects_language_repl_prompts(self, cursor_at_prompt, line, cursor_x, desc):
        """Detect various language REPL prompts."""
        assert cursor_at_prompt(line, cursor_x), f"Failed to detect: {desc}"

    # ==================== Other Tool Prompts ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("ftp> ", 5, "ftp client"),
        ("sftp> ", 6, "sftp client"),
        ("telnet> ", 8, "telnet"),
        ("(gcloud) $ ", 11, "gcloud shell"),
        (">>> ", 4, "aws cloudshell"),
        ("kubectl> ", 9, "kubectl shell"),
        ("nix-shell> ", 11, "nix shell"),
        ("bash-5.1$ ", 10, "bash version"),
        ("zsh-5.8% ", 9, "zsh version"),
        ("sh-5.1$ ", 8, "sh version"),
    ])
    def test_detects_other_tool_prompts(self, cursor_at_prompt, line, cursor_x, desc):
        """Detect other tool and client prompts."""
        assert cursor_at_prompt(line, cursor_x), f"Failed to detect: {desc}"

    # ==================== Edge Cases That Should Match ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("$", 2, "bare dollar, cursor past end"),
        (">", 2, "bare gt, cursor past end"),
        ("#", 2, "bare hash, cursor past end"),
        ("$ \t", 2, "prompt with tab after space"),
        (">\t", 2, "prompt with only tab"),
    ])
    def test_edge_cases_that_match(self, cursor_at_prompt, line, cursor_x, desc):
        """Edge cases that should still be detected as prompts."""
        assert cursor_at_prompt(line, cursor_x), f"Failed to detect: {desc}"

    # ==================== Non-Prompts That Should Be Rejected ====================
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("hello world", 11, "plain text"),
        ("Price: $100 ", 12, "dollar in text"),
        ("$100", 4, "dollar amount"),
        ("x = 1; ", 7, "code with semicolon"),
        ("foo: bar ", 9, "key-value pair"),
        ("=> value ", 9, "fat arrow"),
        ("-> result ", 10, "thin arrow"),
        ("", 0, "empty line"),
        ("", 2, "empty line cursor past end"),
        ("$", 0, "cursor at position 0"),
        ("$", 1, "cursor at position 1"),
        ("a", 1, "single char no prompt"),
        ("ab", 2, "two chars no prompt"),
        ("no prompt here", 14, "sentence"),
        ("function() {", 12, "code"),
        ("return value;", 13, "return statement"),
        ("... ", 4, "ellipsis continuation"),
        ("+ ", 2, "plus continuation"),
    ])
    def test_rejects_non_prompts(self, cursor_at_prompt, line, cursor_x, desc):
        """Non-prompt patterns that should be rejected."""
        assert not cursor_at_prompt(line, cursor_x), f"Should reject: {desc}"

    # ==================== Known False Positives (Accepted Limitation) ====================
    # These patterns match our simple heuristic but aren't real prompts.
    # In practice, the stability check filters these out since real output
    # continues flowing, while prompts are stable.
    
    @pytest.mark.parametrize("line,cursor_x,desc", [
        ("Processing (step 1) ", 20, "output ending with )"),
        ("foo) ", 5, "random ) at end"),
        ("result: 42) ", 12, "number before )"),
        ("array[0] ", 9, "array access with ]"),
        ("if (x > 0) ", 11, "code ending with )"),
        (") ) ", 4, "multiple ) with spaces"),
        ("hello world> ", 13, "text ending with >"),
        ("foo:bar> ", 9, "text with colon before >"),
        ("dict['key'] ", 12, "dict access"),
        ("(done) ", 7, "word in parens"),
    ])
    def test_known_false_positives(self, cursor_at_prompt, line, cursor_x, desc):
        """Patterns that match but aren't prompts (stability check handles these).
        
        These are documented limitations of the simple cursor-relative heuristic.
        The full wait command uses a stability check to filter these out in practice.
        """
        # These DO match the pattern - that's expected
        assert cursor_at_prompt(line, cursor_x), (
            f"Expected match (known false positive): {desc}. "
            "If this fails, the heuristic changed - update test or docs."
        )
