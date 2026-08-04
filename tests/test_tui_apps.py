"""End-to-end tests for common real-world TUIs (htop, mc)."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable

import pytest

from conftest import RunResult, retry_until


def _start_htop(session: str, term_cli: Callable[..., RunResult]) -> None:
    """Start htop in a deterministic mode and wait for UI markers."""
    term_cli("run", "-s", session, "LC_ALL=C htop -d 30 --sort-key=PID", check=True)
    ready = term_cli("wait-for", "-s", session, "-t", "15", "F1Help", "F10Quit")
    assert ready.ok, ready.stderr


def _stop_htop(session: str, term_cli: Callable[..., RunResult]) -> None:
    """Quit htop and wait for prompt."""
    term_cli("send-key", "-s", session, "q")
    term_cli("wait", "-s", session, "-t", "10")


def _first_process_target(capture_text: str) -> tuple[str, int, int] | None:
    """Extract the first visible PID and its pane coordinates."""
    for row, line in enumerate(capture_text.splitlines()):
        m = re.match(r"\s*(\d+)\s+\S+\s+\d+", line)
        if m:
            x = (m.start(1) + m.end(1) - 1) // 2
            return (m.group(1), x, row)
    return None


def _capture_annotate(
    session: str,
    term_cli: Callable[..., RunResult],
    tail: int | None = None,
) -> str:
    """Capture annotated output and return stdout."""
    args = ["capture", "-s", session, "-a"]
    if tail is not None:
        args.extend(["--tail", str(tail)])
    result = term_cli(*args)
    assert result.ok, result.stderr
    return result.stdout


def _annotation_labels_for_bg(capture_text: str, bg: str) -> set[str]:
    """Return individual annotation labels that use a background color."""
    labels: set[str] = set()
    pattern = re.compile(rf"^\s*\d+│\s+(.*?)\s+\[bg:{re.escape(bg)}\]$")
    for line in capture_text.splitlines():
        match = pattern.match(line)
        if match:
            labels.update(label.strip() for label in match.group(1).split(", "))
    return labels


def _has_annotation(capture_text: str, label: str, bg: str) -> bool:
    """Check if *label* appears in any annotation line with [bg:*bg*].

    Annotations may merge multiple labels on the same row/color, e.g.
    ``12│ Memory [Bar], Load average [Text] [bg:white]``.
    A simple ``"Memory [Bar] [bg:white]" in text`` substring check would
    miss that, so we parse each annotation line and check the label list.
    """
    pattern = re.compile(rf"^\s*\d+│\s+(.*?)\s+\[bg:{re.escape(bg)}\]$")
    for line in capture_text.splitlines():
        m = pattern.match(line)
        if m:
            # Labels are comma-separated; check if our target is one of them
            found_labels = [lbl.strip() for lbl in m.group(1).split(", ")]
            if label in found_labels:
                return True
    return False


class TestHtopE2E:
    """Real htop interactions mixing function keys, mouse, scroll, and annotations."""

    def test_setup_meters_clicks_update_annotations(
        self,
        session_factory: Callable[..., str],
        term_cli: Callable[..., RunResult],
    ) -> None:
        if shutil.which("htop") is None:
            pytest.skip("htop not found on PATH")

        session = session_factory(cols=100, rows=32)
        _start_htop(session, term_cli)
        try:
            term_cli("send-key", "-s", session, "F2")
            setup = term_cli("wait-for", "-s", session, "-t", "10", "Categories", "F10Done")
            assert setup.ok, setup.stderr

            term_cli("send-mouse", "-s", session, "--text", "Meters", check=True)
            meters = term_cli("wait-for", "-s", session, "-t", "10", "Column 1", "Available meters")
            assert meters.ok, meters.stderr

            initial_ann = _capture_annotate(session, term_cli)
            assert "Annotations:" in initial_ann
            assert "Screen: alternate" in initial_ann
            assert "Mouse:" in initial_ann

            # Column 2 selection
            term_cli("send-mouse", "-s", session, "--text", "Uptime [Text]", check=True)
            assert retry_until(
                lambda: _has_annotation(_capture_annotate(session, term_cli), "Uptime [Text]", "cyan"),
                timeout=5.0,
                interval=0.15,
            ), "Expected Uptime [Text] to become selected (cyan)"

            # Column 1 selection (color and selected label should change)
            term_cli("send-mouse", "-s", session, "--text", "Swap [Bar]", check=True)
            assert retry_until(
                lambda: (
                    _has_annotation(_capture_annotate(session, term_cli), "Swap [Bar]", "cyan")
                    and _has_annotation(_capture_annotate(session, term_cli), "Uptime [Text]", "white")
                ),
                timeout=5.0,
                interval=0.15,
            ), "Expected selection to move from Uptime [Text] to Swap [Bar]"

            # Move focus back to Column 2, then again to Column 1.
            term_cli("send-mouse", "-s", session, "--text", "Load average [Text]", check=True)
            assert retry_until(
                lambda: (
                    _has_annotation(_capture_annotate(session, term_cli), "Load average [Text]", "cyan")
                    and _has_annotation(_capture_annotate(session, term_cli), "Swap [Bar]", "white")
                ),
                timeout=5.0,
                interval=0.15,
            ), "Expected selection to move to Column 2 (Load average)"

            term_cli("send-mouse", "-s", session, "--text", "Memory [Bar]", check=True)
            assert retry_until(
                lambda: (
                    _has_annotation(_capture_annotate(session, term_cli), "Memory [Bar]", "cyan")
                    and _has_annotation(_capture_annotate(session, term_cli), "Load average [Text]", "white")
                ),
                timeout=5.0,
                interval=0.15,
            ), "Expected selection to move back to Column 1 (Memory)"

            # Available meters list selection + scroll
            # Use "Hostname" — unique on screen, unlike "Swap" which also
            # appears in the Column 1 meters and in "Combined memory and
            # swap usage", making --nth fragile across htop versions/configs.
            term_cli("send-mouse", "-s", session, "--text", "Hostname", check=True)
            assert retry_until(
                lambda: _has_annotation(
                    _capture_annotate(session, term_cli), "Hostname", "cyan"
                ),
                timeout=5.0,
                interval=0.15,
            ), (
                "Expected available-meters 'Hostname' selection mode\n"
                f"{_capture_annotate(session, term_cli)}"
            )

            cyan_before = _annotation_labels_for_bg(
                _capture_annotate(session, term_cli), "cyan"
            )

            term_cli(
                "send-mouse", "-s", session,
                "--text", "Hostname",
                "--scroll-down", "3",
                check=True,
            )
            last_capture = ""

            def available_selection_moved() -> bool:
                nonlocal last_capture
                last_capture = _capture_annotate(session, term_cli)
                cyan_after = _annotation_labels_for_bg(last_capture, "cyan")
                return (
                    "Available meters" in last_capture
                    and "Hostname" not in cyan_after
                    and bool(cyan_after - cyan_before)
                )

            assert retry_until(available_selection_moved, timeout=5.0, interval=0.15), (
                f"Expected another available meter to be selected after scrolling\n"
                f"{last_capture}"
            )
        finally:
            _stop_htop(session, term_cli)

    def test_process_list_scroll_changes_first_visible_pid(
        self,
        session_factory: Callable[..., str],
        term_cli: Callable[..., RunResult],
    ) -> None:
        if shutil.which("htop") is None:
            pytest.skip("htop not found on PATH")

        session = session_factory(cols=100, rows=32)
        _start_htop(session, term_cli)
        try:
            before = term_cli("capture", "-s", session, "--no-annotate")
            assert before.ok, before.stderr
            target = _first_process_target(before.stdout)
            assert target is not None, f"Could not find initial visible PID\n{before.stdout}"
            pid_before, x, y = target

            term_cli(
                "send-mouse", "-s", session,
                "--x", str(x), "--y", str(y),
                "--scroll-down", "3",
                check=True,
            )

            last_capture = ""

            def first_pid_changed() -> bool:
                nonlocal last_capture
                after = term_cli("capture", "-s", session, "--no-annotate")
                if not after.ok:
                    return False
                last_capture = after.stdout
                current = _first_process_target(after.stdout)
                return current is not None and current[0] != pid_before

            assert retry_until(first_pid_changed, timeout=5.0, interval=0.15), (
                f"Expected first visible PID to change after scroll-down "
                f"(before={pid_before})\n{last_capture}"
            )
        finally:
            _stop_htop(session, term_cli)


class TestMcE2E:
    """Real mc interactions combining keys, mouse clicks, scroll, and annotations."""

    def test_mc_menu_via_keys_and_mouse_changes_panel_mode(
        self,
        session: str,
        term_cli: Callable[..., RunResult],
    ) -> None:
        if shutil.which("mc") is None:
            pytest.skip("mc not found on PATH")

        term_cli("resize", "-s", session, "-x", "100", "-y", "30", check=True)
        term_cli("run", "-s", session, "mc", check=True)
        ready = term_cli("wait-for", "-s", session, "-t", "15", "1Help", "10Quit")
        assert ready.ok, ready.stderr

        # Open top menu via keys (F9 then Enter opens Left menu)
        term_cli("send-key", "-s", session, "F9")
        term_cli("send-key", "-s", session, "Enter")
        menu_open = term_cli("wait-for", "-s", session, "-t", "10", "Quick view", "Listing mode")
        assert menu_open.ok, menu_open.stderr

        # Activate menu item via mouse click
        term_cli("send-mouse", "-s", session, "--text", "Info", check=True)
        info_mode = term_cli("wait-for", "-s", session, "-t", "10", "Mode:", "Filesystem:")
        assert info_mode.ok, info_mode.stderr

        ann = _capture_annotate(session, term_cli, tail=20)
        assert "Annotations:" in ann
        assert "Screen: alternate" in ann
        assert "Mouse:" in ann

        # Exit mc so session fixture can return to prompt cleanly
        term_cli("send-key", "-s", session, "F10")
        term_cli("wait", "-s", session, "-t", "10")
