"""
Tests for CLI parsing, command abbreviation, help, and error handling.
"""

from __future__ import annotations

import pytest

from conftest import TERM_CLI


class TestCommandAbbreviation:
    """Tests for command abbreviation feature."""

    def test_full_command_works(self, session, term_cli):
        """Full command names work."""
        # Use session fixture to ensure tmux server is running
        result = term_cli("list")
        assert result.ok

    def test_abbreviation_l_for_list(self, session, term_cli):
        """'l' abbreviates to 'list'."""
        # Use session fixture to ensure tmux server is running
        result = term_cli("l")
        assert result.ok

    def test_abbreviation_li_for_list(self, session, term_cli):
        """'li' abbreviates to 'list'."""
        # Use session fixture to ensure tmux server is running
        result = term_cli("li")
        assert result.ok

    def test_abbreviation_k_for_kill(self, term_cli):
        """'k' abbreviates to 'kill'."""
        # Need --all or --session
        result = term_cli("k", "--all")
        assert result.ok

    def test_abbreviation_st_for_status(self, session, term_cli):
        """'st' is ambiguous (start, status) so requires more chars."""
        result = term_cli("st", "-s", "test")
        assert not result.ok
        assert "Ambiguous command" in result.stderr
        assert "start" in result.stderr
        assert "status" in result.stderr

    def test_abbreviation_star_for_start(self, term_cli):
        """'star' abbreviates to 'start'."""
        from conftest import unique_session_name
        name = unique_session_name()
        try:
            result = term_cli("star", "-s", name)
            assert result.ok
            assert "Created session" in result.stdout
        finally:
            term_cli("kill", "-s", name)

    def test_abbreviation_stat_for_status(self, session, term_cli):
        """'stat' abbreviates to 'status'."""
        result = term_cli("stat", "-s", session)
        assert result.ok
        assert "Session:" in result.stdout

    def test_abbreviation_ru_for_run(self, session, term_cli):
        """'ru' abbreviates to 'run'."""
        result = term_cli("ru", "-s", session, "echo abbrev_test", "-w")
        assert result.ok

    def test_abbreviation_c_for_capture(self, session, term_cli):
        """'c' abbreviates to 'capture'."""
        result = term_cli("c", "-s", session)
        assert result.ok

    def test_abbreviation_res_for_resize(self, session, term_cli):
        """'res' abbreviates to 'resize' ('re' is ambiguous with request*)."""
        result = term_cli("res", "-s", session, "-x", "100")
        assert result.ok

    def test_abbreviation_sc_for_scroll(self, session, term_cli):
        """'sc' abbreviates to 'scroll'."""
        result = term_cli("sc", "-s", session, "5")
        assert result.ok

    def test_wait_full_command_works(self, session, term_cli):
        """'wait' full command works (cannot be abbreviated due to ambiguity with wait-idle)."""
        result = term_cli("wait", "-s", session, "-t", "15")
        assert result.ok

    def test_abbreviation_wait_i_for_wait_idle(self, session, term_cli):
        """'wait-i' abbreviates to 'wait-idle'."""
        result = term_cli("wait-i", "-s", session, "-i", "0.5", "-t", "2")
        assert result.ok

    def test_abbreviation_p_for_pipe_log(self, session, term_cli, tmp_path):
        """'p' abbreviates to 'pipe-log'."""
        logfile = tmp_path / "test.log"
        result = term_cli("p", "-s", session, str(logfile))
        assert result.ok
        term_cli("u", "-s", session)  # unpipe

    def test_abbreviation_u_for_unpipe(self, session, term_cli):
        """'u' abbreviates to 'unpipe'."""
        result = term_cli("u", "-s", session)
        assert result.ok

    def test_abbreviation_send_t_for_send_text(self, session, term_cli):
        """'send-t' abbreviates to 'send-text'."""
        result = term_cli("send-t", "-s", session, "hello")
        assert result.ok

    def test_abbreviation_send_k_for_send_key(self, session, term_cli):
        """'send-k' abbreviates to 'send-key'."""
        result = term_cli("send-k", "-s", session, "Enter")
        assert result.ok

    def test_ambiguous_s_fails(self, term_cli):
        """'s' is ambiguous (start, status, send-text, send-key, send-stdin, scroll)."""
        result = term_cli("s", "-s", "test")
        assert not result.ok
        assert "Ambiguous command" in result.stderr
        assert "could be" in result.stderr

    def test_ambiguous_w_fails(self, term_cli):
        """'w' is ambiguous (wait, wait-idle, wait-for)."""
        result = term_cli("w", "-s", "test")
        assert not result.ok
        assert "Ambiguous command" in result.stderr

    def test_ambiguous_wa_fails(self, term_cli):
        """'wa' is ambiguous (wait, wait-idle, wait-for)."""
        result = term_cli("wa", "-s", "test")
        assert not result.ok
        assert "Ambiguous command" in result.stderr
        assert "wait" in result.stderr
        assert "wait-for" in result.stderr
        assert "wait-idle" in result.stderr

    def test_ambiguous_send_fails(self, term_cli):
        """'send' is ambiguous (send-text, send-key, send-stdin)."""
        result = term_cli("send", "-s", "test", "arg")
        assert not result.ok
        assert "Ambiguous command" in result.stderr

    def test_unknown_command_fails(self, term_cli):
        """Unknown command fails with appropriate error."""
        result = term_cli("nonexistent_command_xyz")
        assert not result.ok
        # Argparse error message
        assert "invalid choice" in result.stderr or "error" in result.stderr.lower()


class TestHelp:
    """Tests for help output."""

    def test_no_command_shows_help(self, term_cli):
        """Running with no arguments shows help."""
        result = term_cli()
        assert result.ok
        assert "usage:" in result.stdout.lower() or "term-cli" in result.stdout

    def test_help_flag(self, term_cli):
        """--help shows help."""
        result = term_cli("--help")
        assert result.ok
        assert "usage:" in result.stdout.lower()
        assert "start" in result.stdout
        assert "kill" in result.stdout
        assert "run" in result.stdout

    def test_h_flag(self, term_cli):
        """-h shows help."""
        result = term_cli("-h")
        assert result.ok
        assert "usage:" in result.stdout.lower()

    def test_command_help(self, term_cli):
        """<command> --help shows command-specific help."""
        result = term_cli("start", "--help")
        assert result.ok
        assert "--session" in result.stdout
        assert "--cwd" in result.stdout

    def test_start_help(self, term_cli):
        """start --help shows start options."""
        result = term_cli("start", "-h")
        assert result.ok
        assert "--cols" in result.stdout or "-x" in result.stdout
        assert "--rows" in result.stdout or "-y" in result.stdout
        assert "--env" in result.stdout or "-e" in result.stdout

    def test_run_help(self, term_cli):
        """run --help shows run options."""
        result = term_cli("run", "-h")
        assert result.ok
        assert "--wait" in result.stdout or "-w" in result.stdout
        assert "--timeout" in result.stdout or "-t" in result.stdout

    def test_capture_help(self, term_cli):
        """capture --help shows capture options."""
        result = term_cli("capture", "-h")
        assert result.ok
        assert "--scrollback" in result.stdout or "-n" in result.stdout
        assert "--tail" in result.stdout or "-t" in result.stdout
        assert "--no-trim" in result.stdout
        assert "--raw" in result.stdout or "-r" in result.stdout

    def test_help_shows_examples(self, term_cli):
        """Main help shows examples."""
        result = term_cli("--help")
        assert "Examples:" in result.stdout or "example" in result.stdout.lower()

    def test_help_shows_short_forms(self, term_cli):
        """Help mentions short forms."""
        result = term_cli("--help")
        assert "Short forms" in result.stdout or "abbreviated" in result.stdout.lower()


class TestShortFlags:
    """Tests for short flag variants."""

    def test_s_for_session(self, session, term_cli):
        """-s works for --session."""
        result = term_cli("status", "-s", session)
        assert result.ok

    def test_w_for_wait(self, session, term_cli):
        """-w works for --wait."""
        result = term_cli("run", "-s", session, "echo test", "-w")
        assert result.ok

    def test_t_for_timeout(self, session, term_cli):
        """-t works for --timeout."""
        result = term_cli("wait", "-s", session, "-t", "1")
        assert result.ok

    def test_x_for_cols(self, term_cli):
        """-x works for --cols."""
        from conftest import unique_session_name
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "-x", "100")
            assert result.ok
        finally:
            term_cli("kill", "-s", name)

    def test_y_for_rows(self, term_cli):
        """-y works for --rows."""
        from conftest import unique_session_name
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "-y", "30")
            assert result.ok
        finally:
            term_cli("kill", "-s", name)

    def test_c_for_cwd(self, term_cli, tmp_path):
        """-c works for --cwd."""
        from conftest import unique_session_name
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "-c", str(tmp_path))
            assert result.ok
        finally:
            term_cli("kill", "-s", name)

    def test_n_for_scrollback(self, session, term_cli):
        """-n works for --scrollback."""
        result = term_cli("capture", "-s", session, "-n", "50")
        assert result.ok

    def test_e_for_enter(self, session, term_cli):
        """-e works for --enter."""
        result = term_cli("send-text", "-s", session, "test", "-e")
        assert result.ok

    def test_e_for_env(self, term_cli):
        """-e works for --env in start."""
        from conftest import unique_session_name
        name = unique_session_name()
        try:
            result = term_cli("start", "-s", name, "-e", "FOO=bar")
            assert result.ok
        finally:
            term_cli("kill", "-s", name)

    def test_r_for_raw(self, session, term_cli, tmp_path):
        """-r works for --raw."""
        logfile = tmp_path / "test.log"
        result = term_cli("pipe-log", "-s", session, str(logfile), "-r")
        assert result.ok
        term_cli("unpipe", "-s", session)

    def test_i_for_idle(self, session, term_cli):
        """-i works for --idle."""
        result = term_cli("wait-idle", "-s", session, "-i", "0.5", "-t", "2")
        assert result.ok

    def test_a_for_all(self, term_cli):
        """-a works for --all."""
        result = term_cli("kill", "-a")
        assert result.ok


class TestErrorHandling:
    """Tests for error conditions and exit codes."""

    def test_missing_required_session(self, term_cli):
        """Missing required --session fails."""
        result = term_cli("run", "echo test")
        assert not result.ok
        # Argparse should complain about missing --session
        assert "required" in result.stderr.lower() or "session" in result.stderr.lower()

    def test_nonexistent_session_error(self, term_cli):
        """Operations on non-existent session fail with clear error."""
        result = term_cli("run", "-s", "nonexistent_session_xyz", "echo hi")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_invalid_timeout_type(self, term_cli, session):
        """Non-numeric timeout fails."""
        result = term_cli("wait", "-s", session, "-t", "not_a_number")
        assert not result.ok

    def test_exit_code_success(self, session, term_cli):
        """Successful commands return exit code 0."""
        result = term_cli("status", "-s", session)
        assert result.returncode == 0

    def test_exit_code_value_error(self, term_cli):
        """ValueError (invalid input) returns exit code 2."""
        result = term_cli("kill")  # Missing --session or --all
        assert result.returncode == 2

    def test_exit_code_nonexistent_session(self, term_cli):
        """Operations on non-existent session return exit code 2 (ValueError)."""
        result = term_cli("status", "-s", "nonexistent_xyz")
        assert result.returncode == 2
