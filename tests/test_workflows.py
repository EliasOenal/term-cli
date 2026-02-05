"""
End-to-end workflow tests with real applications.
"""

from __future__ import annotations

import shutil

import pytest  # type: ignore

from conftest import require_tool, wait_for_content, retry_until, wait_for_file_content


class TestShellWorkflows:
    """Tests using shell features."""

    def test_full_workflow_echo(self, session, term_cli):
        """Complete workflow: start -> run -> capture -> verify."""
        # Run a command
        term_cli("run", "-s", session, "echo 'hello from workflow'", "-w")
        
        # Capture output
        result = term_cli("capture", "-s", session)
        assert "hello from workflow" in result.stdout

    def test_command_history(self, session, term_cli):
        """Test command history with arrow keys."""
        term_cli("run", "-s", session, "echo first_command", "-w")
        term_cli("run", "-s", session, "echo second_command", "-w")
        
        # Press up arrow to recall last command
        term_cli("send-key", "-s", session, "Up")
        assert wait_for_content(term_cli, session, "echo second_command"), "Up arrow didn't recall command"
        
        result = term_cli("capture", "-s", session)
        assert "echo second_command" in result.stdout

    def test_tab_completion(self, session, term_cli, tmp_path):
        """Test tab completion."""
        # Create a file with unique name
        testfile = tmp_path / "unique_test_file_for_completion.txt"
        testfile.write_text("test")
        
        # Change to tmp_path and try to complete
        term_cli("run", "-s", session, f"cd {tmp_path}", "-w")
        term_cli("send-text", "-s", session, "cat unique_test_file_for")
        term_cli("send-key", "-s", session, "Tab")
        assert wait_for_content(term_cli, session, "unique_test_file_for_completion.txt"), "Tab completion failed"
        
        result = term_cli("capture", "-s", session)
        # Tab should complete to the full filename
        assert "unique_test_file_for_completion.txt" in result.stdout, \
            f"Tab completion should complete the filename. Got: {result.stdout}"

    def test_interrupt_running_process(self, session, term_cli):
        """Test Ctrl+C interrupts a running process."""
        term_cli("run", "-s", session, "sleep 100")
        # Wait for sleep to start
        def check_sleep_running():
            result = term_cli("status", "-s", session)
            return "sleep" in result.stdout
        assert retry_until(check_sleep_running, timeout=3.0), "sleep never started"
        
        # Interrupt
        term_cli("send-key", "-s", session, "C-c")
        
        # Should be back at prompt
        result = term_cli("wait", "-s", session, "-t", "5")
        assert "Prompt detected" in result.stdout

    def test_background_process(self, session, term_cli):
        """Test running process in background."""
        term_cli("run", "-s", session, "sleep 100 &", "-w")
        
        # Should return to prompt while sleep runs in background
        # The wait should detect the prompt since the command was backgrounded
        result = term_cli("wait", "-s", session, "-t", "2")
        assert "Prompt detected" in result.stdout, \
            "Backgrounded command should return to prompt immediately"
        
        # We can run another command while background job runs
        term_cli("run", "-s", session, "echo foreground_works", "-w")
        capture = term_cli("capture", "-s", session)
        assert "foreground_works" in capture.stdout
        
        # Clean up background job
        term_cli("run", "-s", session, "kill %1 2>/dev/null || true", "-w")

    def test_pipe_commands(self, session, term_cli):
        """Test piping between commands."""
        term_cli("run", "-s", session, "echo -e 'line1\\nline2\\nline3' | grep line2", "-w")
        
        result = term_cli("capture", "-s", session)
        assert "line2" in result.stdout

    def test_environment_variables(self, session, term_cli):
        """Test setting and using environment variables."""
        term_cli("run", "-s", session, "export MY_VAR='test_value'", "-w")
        term_cli("run", "-s", session, "echo $MY_VAR", "-w")
        
        result = term_cli("capture", "-s", session)
        assert "test_value" in result.stdout


class TestPythonRepl:
    """Tests with Python REPL."""

    @pytest.fixture(autouse=True)
    def check_python(self):
        require_tool("python3")

    def test_python_repl_basic(self, session, term_cli):
        """Start Python REPL and run basic commands."""
        term_cli("run", "-s", session, "python3")
        term_cli("wait", "-s", session, "-t", "5")
        
        term_cli("send-text", "-s", session, "2 + 2", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        
        result = term_cli("capture", "-s", session)
        assert "4" in result.stdout
        
        term_cli("send-text", "-s", session, "exit()", "-e")

    def test_python_multiline(self, session, term_cli):
        """Test multiline Python code."""
        term_cli("run", "-s", session, "python3")
        term_cli("wait", "-s", session, "-t", "5")
        
        # Define a function and call it
        term_cli("send-text", "-s", session, "def greet(name):", "-e")
        term_cli("send-text", "-s", session, "    return f'Hello, {name}!'", "-e")
        term_cli("send-text", "-s", session, "", "-e")
        term_cli("send-text", "-s", session, "print(greet('World'))", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        
        result = term_cli("capture", "-s", session)
        assert "Hello, World!" in result.stdout
        
        term_cli("send-text", "-s", session, "exit()", "-e")

    def test_python_import(self, session, term_cli):
        """Test importing modules in Python."""
        term_cli("run", "-s", session, "python3")
        term_cli("wait", "-s", session, "-t", "5")
        
        term_cli("send-text", "-s", session, "import json", "-e")
        term_cli("send-text", "-s", session, "print(json.dumps({'key': 'value'}))", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        
        result = term_cli("capture", "-s", session)
        assert '{"key": "value"}' in result.stdout
        
        term_cli("send-text", "-s", session, "exit()", "-e")

    def test_python_error_handling(self, session, term_cli):
        """Test Python error output."""
        term_cli("run", "-s", session, "python3")
        term_cli("wait", "-s", session, "-t", "5")
        
        term_cli("send-text", "-s", session, "1/0", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        
        result = term_cli("capture", "-s", session)
        assert "ZeroDivisionError" in result.stdout
        
        term_cli("send-text", "-s", session, "exit()", "-e")


class TestNodeRepl:
    """Tests with Node.js REPL."""

    @pytest.fixture(autouse=True)
    def check_node(self):
        if shutil.which("node") is None:
            pytest.skip("node not found on PATH")

    def test_node_repl_basic(self, session, term_cli):
        """Start Node REPL and run basic commands."""
        term_cli("run", "-s", session, "node")
        term_cli("wait", "-s", session, "-t", "5")
        
        term_cli("send-text", "-s", session, "2 + 2", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        
        result = term_cli("capture", "-s", session)
        assert "4" in result.stdout
        
        term_cli("send-key", "-s", session, "C-d")

    def test_node_json(self, session, term_cli):
        """Test JSON handling in Node."""
        term_cli("run", "-s", session, "node")
        term_cli("wait", "-s", session, "-t", "5")
        
        term_cli("send-text", "-s", session, "JSON.stringify({hello: 'world'})", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        
        result = term_cli("capture", "-s", session)
        assert "hello" in result.stdout and "world" in result.stdout
        
        term_cli("send-key", "-s", session, "C-d")


class TestViWorkflow:
    """Tests with vi/vim editor."""

    @pytest.fixture(autouse=True)
    def check_vi(self):
        if shutil.which("vi") is None and shutil.which("vim") is None:
            pytest.skip("vi/vim not found on PATH")

    def test_vi_open_and_quit(self, session, term_cli, tmp_path):
        """Open vi and quit without saving."""
        testfile = tmp_path / "test.txt"
        
        term_cli("run", "-s", session, f"vi {testfile}")
        term_cli("wait-idle", "-s", session, "-i", "0.3", "-t", "5")
        
        # Quit without saving
        term_cli("send-key", "-s", session, "Escape")
        term_cli("send-text", "-s", session, ":q!", "-e")
        
        # Should be back at shell
        result = term_cli("wait", "-s", session, "-t", "5")
        assert "Prompt detected" in result.stdout

    def test_vi_edit_and_save(self, session, term_cli, tmp_path):
        """Open vi, add content, and save."""
        testfile = tmp_path / "test.txt"
        
        term_cli("run", "-s", session, f"vi {testfile}")
        term_cli("wait-idle", "-s", session, "-i", "0.3", "-t", "5")
        
        # Insert mode and add text
        term_cli("send-key", "-s", session, "i")
        term_cli("send-text", "-s", session, "Hello from vi!")
        term_cli("send-key", "-s", session, "Escape")
        
        # Save and quit
        term_cli("send-text", "-s", session, ":wq", "-e")
        term_cli("wait", "-s", session, "-t", "5")
        
        # Verify file was created
        assert testfile.exists()
        assert "Hello from vi!" in testfile.read_text()

    def test_vi_navigation(self, session, term_cli, tmp_path):
        """Test vi navigation commands."""
        testfile = tmp_path / "test.txt"
        testfile.write_text("line1\nline2\nline3\n")
        
        term_cli("run", "-s", session, f"vi {testfile}")
        term_cli("wait-idle", "-s", session, "-i", "0.3", "-t", "5")
        
        # Navigate with j (down) and k (up)
        term_cli("send-key", "-s", session, "j")  # Move down
        term_cli("send-key", "-s", session, "j")  # Move down again
        
        # Go to end of file
        term_cli("send-key", "-s", session, "G")
        
        # Quit
        term_cli("send-text", "-s", session, ":q", "-e")
        term_cli("wait", "-s", session, "-t", "5")


class TestLessWorkflow:
    """Tests with less pager."""

    @pytest.fixture(autouse=True)
    def check_less(self):
        require_tool("less")

    def test_less_view_and_quit(self, session, term_cli, tmp_path):
        """Open less and quit."""
        testfile = tmp_path / "test.txt"
        testfile.write_text("\n".join([f"Line {i}" for i in range(100)]))
        
        term_cli("run", "-s", session, f"less {testfile}")
        term_cli("wait-idle", "-s", session, "-i", "0.3", "-t", "5")  # Wait for less to initialize
        
        result = term_cli("capture", "-s", session)
        assert "Line 0" in result.stdout
        
        # Quit
        term_cli("send-key", "-s", session, "q")
        
        result = term_cli("wait", "-s", session, "-t", "2")
        assert "Prompt detected" in result.stdout

    def test_less_navigation(self, session, term_cli, tmp_path):
        """Test less navigation."""
        testfile = tmp_path / "test.txt"
        testfile.write_text("\n".join([f"Line {i}" for i in range(100)]))
        
        term_cli("run", "-s", session, f"less {testfile}")
        term_cli("wait-idle", "-s", session, "-i", "0.3", "-t", "5")  # Wait for less to initialize
        
        # Verify we see the first lines initially
        result_before = term_cli("capture", "-s", session)
        assert "Line 0" in result_before.stdout
        
        # Page down
        term_cli("send-key", "-s", session, "Space")
        term_cli("wait-idle", "-s", session, "-i", "0.2", "-t", "5")  # Wait for scroll to complete
        
        result = term_cli("capture", "-s", session)
        # Should have scrolled past first lines - Line 0 should no longer be visible
        # (a page down in default 24-row terminal scrolls ~23 lines)
        assert "Line 0" not in result.stdout, \
            f"After page down, Line 0 should have scrolled off screen. Got: {result.stdout}"
        # But we should see later lines
        assert any(f"Line {i}" in result.stdout for i in range(20, 50)), \
            f"After page down, should see lines 20-50. Got: {result.stdout}"
        
        # Quit
        term_cli("send-key", "-s", session, "q")

    def test_less_search(self, session, term_cli, tmp_path):
        """Test less search functionality."""
        testfile = tmp_path / "test.txt"
        testfile.write_text("\n".join([f"Line {i}" for i in range(100)]))
        
        term_cli("run", "-s", session, f"less {testfile}")
        term_cli("wait-idle", "-s", session, "-i", "0.3", "-t", "5")  # Wait for less to initialize
        
        # Search for Line 50
        term_cli("send-text", "-s", session, "/Line 50", "-e")
        term_cli("wait-idle", "-s", session, "-i", "0.2", "-t", "5")  # Wait for search to complete
        
        result = term_cli("capture", "-s", session)
        assert "Line 50" in result.stdout
        
        # Quit
        term_cli("send-key", "-s", session, "q")


class TestConcurrency:
    """Tests for concurrent session usage."""

    def test_multiple_sessions_independent(self, session_factory, term_cli):
        """Multiple sessions operate independently."""
        s1 = session_factory()
        s2 = session_factory()
        
        # Run different commands in each
        term_cli("run", "-s", s1, "export VAR=session1", "-w")
        term_cli("run", "-s", s2, "export VAR=session2", "-w")
        
        term_cli("run", "-s", s1, "echo $VAR", "-w")
        term_cli("run", "-s", s2, "echo $VAR", "-w")
        
        # Each should have its own value
        r1 = term_cli("capture", "-s", s1)
        r2 = term_cli("capture", "-s", s2)
        
        assert "session1" in r1.stdout
        assert "session2" in r2.stdout

    def test_rapid_commands(self, session, term_cli):
        """Rapid successive commands don't race."""
        # Send many commands quickly
        for i in range(10):
            term_cli("run", "-s", session, f"echo rapid_{i}", "-w")
        
        result = term_cli("capture", "-s", session, "-n", "50")
        # All should be present
        for i in range(10):
            assert f"rapid_{i}" in result.stdout


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_long_output(self, session, term_cli):
        """Handle commands with long output."""
        term_cli("run", "-s", session, "seq 1 100", "-w")
        
        result = term_cli("capture", "-s", session, "-n", "200")
        assert "1" in result.stdout
        assert "100" in result.stdout

    def test_binary_like_output(self, session, term_cli):
        """Handle output that might look binary."""
        term_cli("run", "-s", session, "printf '\\x00\\x01\\x02'", "-w")
        
        result = term_cli("capture", "-s", session)
        # Should not crash and should return successfully
        assert result.ok
        # The capture should contain some output (the prompt at minimum)
        assert len(result.stdout) > 0

    def test_very_long_command(self, session, term_cli):
        """Handle very long command strings."""
        long_arg = "x" * 500
        term_cli("run", "-s", session, f"echo {long_arg}", "-w")
        
        result = term_cli("capture", "-s", session)
        assert "xxx" in result.stdout

    def test_special_shell_characters(self, session, term_cli):
        """Handle special shell characters."""
        term_cli("run", "-s", session, "echo 'test$var'", "-w")
        
        result = term_cli("capture", "-s", session)
        assert "test$var" in result.stdout

    def test_empty_command(self, session, term_cli):
        """Handle empty/whitespace commands."""
        # Just press enter
        result = term_cli("run", "-s", session, "", "-w")
        assert result.ok
        assert "Command completed" in result.stdout
        
        # Should still be at a working prompt
        capture = term_cli("capture", "-s", session)
        assert capture.ok

    def test_session_reuse(self, term_cli):
        """Can kill and recreate session with same name."""
        from conftest import unique_session_name
        name = unique_session_name()
        
        try:
            # Create, use, kill
            term_cli("start", "-s", name)
            term_cli("run", "-s", name, "echo first_instance", "-w")
            term_cli("kill", "-s", name)
            
            # Recreate with same name
            term_cli("start", "-s", name)
            term_cli("run", "-s", name, "echo second_instance", "-w")
            
            result = term_cli("capture", "-s", name)
            assert "second_instance" in result.stdout
            # Should NOT have first instance output
            assert "first_instance" not in result.stdout
        finally:
            term_cli("kill", "-s", name)


class TestComplexWorkflows:
    """Complex multi-step workflow tests combining multiple utilities."""

    def test_cat_to_file_to_vi_edit(self, session, term_cli, tmp_path):
        """Complex workflow: cat to create file -> vi to edit -> verify changes.
        
        This tests a realistic agent workflow:
        1. Use cat with stdin to create a file
        2. Use vi to add more content
        3. Verify the final file contents
        """
        testfile = tmp_path / "workflow_test.txt"
        
        # Step 1: Use cat to create initial file
        term_cli("run", "-s", session, f"cat > {testfile}")
        term_cli("send-text", "-s", session, "Initial line 1")
        term_cli("send-key", "-s", session, "Enter")
        term_cli("send-text", "-s", session, "Initial line 2")
        term_cli("send-key", "-s", session, "Enter")
        term_cli("send-key", "-s", session, "C-d")  # EOF to finish cat
        
        # Verify file was created
        result = term_cli("wait", "-s", session, "-t", "2")
        assert "Prompt detected" in result.stdout
        assert testfile.exists()
        content = testfile.read_text()
        assert "Initial line 1" in content
        assert "Initial line 2" in content
        
        # Step 2: Use vi to add more content
        if shutil.which("vi") is None and shutil.which("vim") is None:
            pytest.skip("vi/vim not found")
        
        term_cli("run", "-s", session, f"vi {testfile}")
        term_cli("wait-idle", "-s", session, "-i", "0.3", "-t", "5")
        
        # Go to end of file and add a line
        term_cli("send-key", "-s", session, "G")  # Go to last line
        term_cli("send-key", "-s", session, "o")  # Open new line below
        term_cli("send-text", "-s", session, "Added by vi")
        term_cli("send-key", "-s", session, "Escape")
        term_cli("send-text", "-s", session, ":wq", "-e")  # Save and quit
        
        # Verify vi changes
        result = term_cli("wait", "-s", session, "-t", "2")
        assert "Prompt detected" in result.stdout
        
        final_content = testfile.read_text()
        assert "Initial line 1" in final_content
        assert "Initial line 2" in final_content
        assert "Added by vi" in final_content

    def test_status_during_running_process(self, session, term_cli):
        """Test status command shows running state during long process.
        
        This tests that the status command accurately reflects process state.
        """
        # Start a long-running process
        term_cli("run", "-s", session, "sleep 10")
        
        # Wait for status to show running state
        def check_running():
            result = term_cli("status", "-s", session)
            return "State: running" in result.stdout and "Foreground: sleep" in result.stdout
        retry_until(check_running, timeout=5.0)
        
        # Interrupt the process
        term_cli("send-key", "-s", session, "C-c")
        
        # Wait for status to show idle state
        def check_idle():
            result = term_cli("status", "-s", session)
            return "State: idle" in result.stdout
        retry_until(check_idle, timeout=5.0)

    def test_send_stdin_to_python_repl(self, session, term_cli, tmux_socket):
        """Test send-stdin command with Python REPL.
        
        Send multiline Python code via send-stdin to the Python REPL.
        """
        require_tool("python3")
        import subprocess
        from conftest import TERM_CLI
        
        # Start Python REPL and wait for prompt
        term_cli("run", "-s", session, "python3")
        term_cli("wait", "-s", session, "-t", "5")
        
        # Send multiline Python code via send-stdin
        python_code = "x = 42\nprint(f'The answer is {x}')\n"
        proc = subprocess.run(
            [TERM_CLI, "-L", tmux_socket, "send-stdin", "-s", session],
            input=python_code,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        
        # Wait for prompt to return after code executes
        term_cli("wait", "-s", session, "-t", "5")
        
        result = term_cli("capture", "-s", session)
        assert "The answer is 42" in result.stdout
        
        # Exit Python
        term_cli("send-text", "-s", session, "exit()", "-e")

    def test_wait_for_server_ready(self, session, term_cli, tmp_path):
        """Test wait-for command to detect server readiness.
        
        Simulates waiting for a server to start by looking for a ready message.
        """
        # Create a script that simulates server startup
        script = tmp_path / "fake_server.sh"
        script.write_text("""#!/bin/bash
echo "Starting server..."
sleep 1
echo "Loading configuration..."
sleep 1
echo "Server ready on port 8080"
sleep 10
""")
        script.chmod(0o755)
        
        term_cli("run", "-s", session, str(script))
        
        # Wait for the ready message
        result = term_cli("wait-for", "-s", session, "Server ready", "-t", "10", "-c")
        assert result.ok
        assert "Pattern detected" in result.stdout
        assert "Server ready on port 8080" in result.stdout
        
        # Clean up
        term_cli("send-key", "-s", session, "C-c")

    def test_pipe_log_capture_and_analyze(self, session, term_cli, tmp_path):
        """Test pipe-log workflow: run command, capture log, analyze output.
        
        This tests a realistic debugging workflow where output is logged.
        """
        logfile = tmp_path / "output.log"
        
        # Start logging
        term_cli("pipe-log", "-s", session, str(logfile))
        
        # Run some commands that produce output
        term_cli("run", "-s", session, "echo 'Start of test'", "-w")
        term_cli("run", "-s", session, "for i in 1 2 3; do echo \"Processing item $i\"; done", "-w")
        term_cli("run", "-s", session, "echo 'End of test'", "-w")
        
        # Wait for log file to contain the expected content
        wait_for_file_content(logfile, "End of test", timeout=5.0)
        
        # Stop logging
        term_cli("unpipe", "-s", session)
        
        # Verify log file contains the output
        assert logfile.exists()
        log_content = logfile.read_text()
        assert "Start of test" in log_content
        assert "Processing item 1" in log_content
        assert "Processing item 2" in log_content
        assert "Processing item 3" in log_content
        assert "End of test" in log_content
