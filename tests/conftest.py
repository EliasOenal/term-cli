"""
Shared fixtures and utilities for term-cli integration tests.

Socket Isolation:
Each test module (file) gets its own tmux socket via the -L option, preventing
parallel pytest-xdist workers from interfering with each other. The socket name
is derived from the test file name + a unique ID.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generator

import pytest

# Path to term-cli executable
TERM_CLI = Path(__file__).parent.parent / "term-cli"
# Path to term-assist executable
TERM_ASSIST = Path(__file__).parent.parent / "term-assist"

# Track sockets to clean up (module-level for atexit)
_sockets_to_cleanup: set[str] = set()


@dataclass
class RunResult:
    """Result of running term-cli."""
    returncode: int
    stdout: str
    stderr: str
    
    @property
    def ok(self) -> bool:
        return self.returncode == 0


def require_tool(name: str) -> None:
    """Fail test with clear message if required tool is not found."""
    if shutil.which(name) is None:
        pytest.fail(f"Required tool '{name}' not found on PATH")


def unique_session_name() -> str:
    """Generate a unique session name for testing."""
    return f"test_{uuid.uuid4().hex[:8]}"


def cleanup_session(tmux_socket: str, name: str, term_cli: Callable[..., RunResult]) -> None:
    """Clean up a session before killing it.
    
    This handles:
    1. Unlocking the session (in case test locked it via term-assist)
    2. Killing the session
    """
    subprocess.run(
        ["tmux", "-L", tmux_socket, "set-option", "-t", f"={name}:", "-u", "@term_cli_agent_locked"],
        capture_output=True,
    )
    term_cli("kill", "-s", name)


def _cleanup_socket(socket_name: str) -> None:
    """Kill the tmux server for a socket."""
    subprocess.run(
        ["tmux", "-L", socket_name, "kill-server"],
        capture_output=True,
    )


def _register_socket_cleanup(socket_name: str) -> None:
    """Register a socket for cleanup at exit."""
    if socket_name not in _sockets_to_cleanup:
        _sockets_to_cleanup.add(socket_name)


def _cleanup_all_sockets() -> None:
    """Clean up all registered sockets."""
    for socket_name in _sockets_to_cleanup:
        _cleanup_socket(socket_name)


# Register atexit handler to clean up sockets even if tests crash
atexit.register(_cleanup_all_sockets)


@pytest.fixture(scope="module")
def tmux_socket(request: pytest.FixtureRequest) -> Generator[str, None, None]:
    """
    Module-scoped fixture providing an isolated tmux socket.
    
    Each test module gets its own tmux server, preventing parallel
    pytest-xdist workers from interfering with each other.
    
    Creates a keepalive session to prevent the server from exiting when
    test sessions are cleaned up between tests.
    """
    # Get test module name for readable socket names
    # request.path is the modern API (pytest 7+), fspath is deprecated
    if hasattr(request, 'path') and request.path:
        module_name = request.path.stem
    else:
        module_name = "test"
    socket_name = f"pytest_{module_name}_{uuid.uuid4().hex[:8]}"
    
    _register_socket_cleanup(socket_name)
    
    # Create a keepalive session to prevent server from exiting when
    # all test sessions are killed between tests
    subprocess.run(
        ["tmux", "-L", socket_name, "new-session", "-d", "-s", "_keepalive"],
        capture_output=True,
    )
    
    yield socket_name
    
    # Kill the tmux server when the module is done
    _cleanup_socket(socket_name)
    _sockets_to_cleanup.discard(socket_name)


@pytest.fixture
def term_cli(tmux_socket: str) -> Callable[..., RunResult]:
    """
    Fixture providing a helper function to run term-cli commands.
    
    All commands automatically use the isolated tmux socket for this test module.
    
    Usage:
        result = term_cli("start", "-s", "mysession")
        assert result.ok
        assert "Created" in result.stdout
    """
    def run(*args: str, check: bool = False, timeout: float = 30.0) -> RunResult:
        # Prepend socket option to all commands
        full_args = ["-L", tmux_socket, *args]
        result = subprocess.run(
            [str(TERM_CLI), *full_args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        run_result = RunResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        if check and not run_result.ok:
            raise AssertionError(
                f"term-cli {' '.join(full_args)} failed with code {result.returncode}:\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
        return run_result
    return run


@pytest.fixture
def term_assist(tmux_socket: str) -> Callable[..., RunResult]:
    """
    Fixture providing a helper function to run term-assist commands.
    
    Uses the same isolated tmux socket as term_cli for this test module.
    
    Usage:
        result = term_assist("done", "-s", "mysession")
        assert result.ok
    """
    import sys
    def run(*args: str, timeout: float = 30.0) -> RunResult:
        # Prepend socket option to all commands
        full_args = ["-L", tmux_socket, *args]
        result = subprocess.run(
            [sys.executable, str(TERM_ASSIST), *full_args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return RunResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return run


@pytest.fixture
def session(term_cli: Callable[..., RunResult], tmux_socket: str) -> Generator[str, None, None]:
    """
    Fixture that creates a unique session and cleans it up after the test.
    
    Usage:
        def test_something(session, term_cli):
            term_cli("run", "-s", session, "echo hello")
    """
    name = unique_session_name()
    result = term_cli("start", "-s", name)
    if not result.ok:
        pytest.fail(f"Failed to create session '{name}': {result.stderr}")
    
    # Wait for shell prompt to be ready before yielding
    # Use 30s timeout to handle system load during parallel test execution
    wait_result = term_cli("wait", "-s", name, "-t", "30")
    if not wait_result.ok:
        pytest.fail(f"Shell prompt not ready in session '{name}': {wait_result.stderr}")
    
    yield name
    
    cleanup_session(tmux_socket, name, term_cli)


@pytest.fixture
def session_factory(term_cli: Callable[..., RunResult], tmux_socket: str) -> Generator[Callable[..., str], None, None]:
    """
    Fixture that provides a factory to create multiple sessions.
    All created sessions are cleaned up after the test.
    
    Usage:
        def test_multiple_sessions(session_factory, term_cli):
            s1 = session_factory()
            s2 = session_factory(cols=120, rows=40)
    """
    created_sessions: list[str] = []
    
    def create(
        name: str | None = None,
        cols: int | None = None,
        rows: int | None = None,
        cwd: str | None = None,
    ) -> str:
        session_name = name or unique_session_name()
        args = ["start", "-s", session_name]
        if cols is not None:
            args.extend(["-x", str(cols)])
        if rows is not None:
            args.extend(["-y", str(rows)])
        if cwd is not None:
            args.extend(["-c", cwd])
        
        result = term_cli(*args)
        if not result.ok:
            pytest.fail(f"Failed to create session '{session_name}': {result.stderr}")
        
        # Wait for shell prompt to be ready
        # Use 30s timeout to handle system load during parallel test execution
        wait_result = term_cli("wait", "-s", session_name, "-t", "30")
        if not wait_result.ok:
            pytest.fail(f"Shell prompt not ready in session '{session_name}': {wait_result.stderr}")
        
        created_sessions.append(session_name)
        return session_name
    
    yield create
    
    # Cleanup all created sessions
    for name in created_sessions:
        cleanup_session(tmux_socket, name, term_cli)


@pytest.fixture
def temp_file(tmp_path: Path) -> Path:
    """Provide a temporary file path for logging tests."""
    return tmp_path / "output.log"


def capture_content(
    term_cli: Callable[..., RunResult],
    session: str,
) -> str:
    """Capture screen content with wrapped lines joined (via --scrollback).

    Use this for substring assertions on typed/echoed text that may wrap
    across physical screen rows (e.g. when a long hostname makes the shell
    prompt exceed the terminal width).

    For testing physical screen layout or capture rendering, use
    term_cli("capture", "--session", ...) directly instead.
    """
    result = term_cli("capture", "--session", session, "--scrollback", "500")
    return result.stdout


def wait_for_content(
    term_cli: Callable[..., RunResult],
    session: str,
    content: str,
    timeout: float = 5.0,
    interval: float = 0.1,
) -> bool:
    """
    Wait until the captured screen contains the expected content.
    Uses scrollback capture to join wrapped lines, so substring matching
    works regardless of prompt length or terminal width.
    Returns True if found, False if timeout.
    """
    start = time.time()
    while time.time() - start < timeout:
        if content in capture_content(term_cli, session):
            return True
        time.sleep(interval)
    return False


def wait_for_prompt(
    term_cli: Callable[..., RunResult],
    session: str,
    timeout: float = 5.0,
) -> bool:
    """Wait for shell prompt to appear."""
    result = term_cli("wait", "-s", session, "-t", str(timeout))
    return "Prompt detected" in result.stdout


def wait_for_idle(
    term_cli: Callable[..., RunResult],
    session: str,
    idle_seconds: float = 0.3,
    timeout: float = 5.0,
) -> bool:
    """Wait for terminal output to stop changing."""
    result = term_cli("wait-idle", "-s", session, "-i", str(idle_seconds), "-t", str(timeout))
    return result.ok


def retry_until(
    func: Callable[[], bool],
    timeout: float = 5.0,
    interval: float = 0.1,
) -> bool:
    """
    Retry a function until it returns True or timeout.
    Useful for replacing fixed sleeps with polling in threading tests.
    """
    start = time.time()
    while time.time() - start < timeout:
        if func():
            return True
        time.sleep(interval)
    return False


def wait_for_file_content(
    filepath: Path,
    content: str,
    timeout: float = 5.0,
    interval: float = 0.1,
) -> bool:
    """
    Wait until file contains expected content.
    Useful for waiting on pipe-log output to be flushed.
    """
    start = time.time()
    while time.time() - start < timeout:
        if filepath.exists():
            try:
                text = filepath.read_text()
                if content in text:
                    return True
            except OSError:
                pass  # File may be locked, retry
        time.sleep(interval)
    return False


# Check for required tools at module load time
def pytest_configure(config: pytest.Config) -> None:
    """Verify tmux is available before running tests."""
    if shutil.which("tmux") is None:
        raise pytest.UsageError("tmux is required to run tests but was not found on PATH")
    # Register the serial marker
    config.addinivalue_line(
        "markers", "serial: mark test that uses global tmux state (run separately from parallel tests)"
    )
