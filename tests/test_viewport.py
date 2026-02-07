"""
Tests for viewport commands: resize, scroll.
"""

from __future__ import annotations


class TestResize:
    """Tests for the 'resize' command."""

    def test_resize_both_dimensions(self, session, term_cli):
        """resize with both cols and rows works."""
        result = term_cli("resize", "-s", session, "-x", "100", "-y", "50")
        assert result.ok
        assert "100x50" in result.stdout
        
        # Verify via status
        status = term_cli("status", "-s", session)
        assert "100x50" in status.stdout

    def test_resize_cols_only(self, session, term_cli):
        """resize with only cols keeps rows."""
        # Get initial size (via status)
        status = term_cli("status", "-s", session)
        # Default is 80x24
        
        result = term_cli("resize", "-s", session, "-x", "120")
        assert result.ok
        assert "120x" in result.stdout

    def test_resize_rows_only(self, session, term_cli):
        """resize with only rows keeps cols."""
        result = term_cli("resize", "-s", session, "-y", "40")
        assert result.ok
        assert "x40" in result.stdout

    def test_resize_requires_dimension(self, term_cli, session):
        """resize without any dimension raises error."""
        result = term_cli("resize", "-s", session)
        assert not result.ok
        assert "Must specify" in result.stderr

    def test_resize_small(self, session, term_cli):
        """resize to small dimensions works."""
        result = term_cli("resize", "-s", session, "-x", "20", "-y", "10")
        assert result.ok
        assert "20x10" in result.stdout

    def test_resize_large(self, session, term_cli):
        """resize to large dimensions works."""
        result = term_cli("resize", "-s", session, "-x", "300", "-y", "100")
        assert result.ok
        assert "300x100" in result.stdout

    def test_resize_affects_output(self, session, term_cli):
        """resize affects how output wraps."""
        # Resize to narrow
        term_cli("resize", "-s", session, "-x", "40", "-y", "24")
        
        # Run command that outputs a 50-char string (will wrap at 40 cols)
        output_str = "x" * 50
        term_cli("run", "-s", session, f"echo {output_str}", "-w")
        result = term_cli("capture", "-s", session)
        
        # Output should be wrapped - the 50 chars should span multiple lines
        # because the terminal is only 40 columns wide
        assert result.ok
        assert "xxx" in result.stdout
        # Count lines containing x's - should be at least 2 due to wrapping
        x_lines = [line for line in result.stdout.split('\n') if 'xxx' in line]
        assert len(x_lines) >= 2, \
            f"50-char output in 40-col terminal should wrap to multiple lines, got: {result.stdout}"

    def test_resize_nonexistent_session(self, term_cli):
        """resize on non-existent session raises error."""
        result = term_cli("resize", "-s", "nonexistent_xyz", "-x", "100")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_resize_zero_cols(self, session, term_cli):
        """resize with zero cols is rejected by tmux."""
        result = term_cli("resize", "-s", session, "-x", "0")
        assert not result.ok
        assert result.returncode == 1  # RuntimeError from tmux
        assert "too small" in result.stderr.lower() or "width" in result.stderr.lower()

    def test_resize_zero_rows(self, session, term_cli):
        """resize with zero rows is rejected by tmux."""
        result = term_cli("resize", "-s", session, "-y", "0")
        assert not result.ok
        assert result.returncode == 1  # RuntimeError from tmux
        assert "too small" in result.stderr.lower() or "height" in result.stderr.lower()

    def test_resize_preserves_content(self, session, term_cli):
        """resize preserves existing screen content."""
        term_cli("run", "-s", session, "echo preserve_me", "-w")
        term_cli("resize", "-s", session, "-x", "120", "-y", "40")
        
        result = term_cli("capture", "-s", session)
        assert "preserve_me" in result.stdout


class TestScroll:
    """Tests for the 'scroll' command."""

    def test_scroll_down(self, session, term_cli):
        """scroll with positive number scrolls down."""
        # Generate some output first
        for i in range(10):
            term_cli("run", "-s", session, f"echo line{i}", "-w")
        
        result = term_cli("scroll", "-s", session, "5")
        assert result.ok
        assert "Scrolled down 5 lines" in result.stdout

    def test_scroll_up(self, session, term_cli):
        """scroll with negative number scrolls up."""
        # Generate some output first
        for i in range(10):
            term_cli("run", "-s", session, f"echo line{i}", "-w")
        
        result = term_cli("scroll", "-s", session, "-5")
        assert result.ok
        assert "Scrolled up 5 lines" in result.stdout

    def test_scroll_zero(self, session, term_cli):
        """scroll with zero fails with validation error."""
        result = term_cli("scroll", "-s", session, "0")
        assert not result.ok
        assert result.returncode == 2
        assert "non-zero" in result.stderr.lower()

    def test_scroll_large_number(self, session, term_cli):
        """scroll with large number works (even if not that much content)."""
        result = term_cli("scroll", "-s", session, "-100")
        assert result.ok
        assert "100 lines" in result.stdout

    def test_scroll_nonexistent_session(self, term_cli):
        """scroll on non-existent session raises error."""
        result = term_cli("scroll", "-s", "nonexistent_xyz", "5")
        assert not result.ok
        assert "does not exist" in result.stderr

    def test_scroll_non_integer_fails(self, term_cli, session):
        """scroll with non-integer value fails."""
        result = term_cli("scroll", "-s", session, "not_a_number")
        assert not result.ok
        # argparse should reject this
        assert "invalid" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_scroll_after_output(self, session, term_cli):
        """scroll allows viewing scrollback after output."""
        # Generate enough output to create scrollback
        for i in range(30):
            term_cli("run", "-s", session, f"echo scrollback_line_{i}", "-w")
        
        # The latest lines should be visible
        result_before = term_cli("capture", "-s", session)
        # line_29 (the last one) should be visible
        assert "scrollback_line_29" in result_before.stdout
        
        # Scroll up to see earlier content
        term_cli("scroll", "-s", session, "-20")
        
        # Capture should show scrolled position - earlier lines should now be visible
        result = term_cli("capture", "-s", session)
        assert result.ok
        # After scrolling up 20 lines, we should see some earlier lines
        # that weren't visible before (approximately lines 0-15)
        has_earlier_lines = any(f"scrollback_line_{i}" in result.stdout for i in range(10))
        assert has_earlier_lines, \
            f"After scrolling up, should see earlier lines. Got: {result.stdout}"
