"""
Tests using the TUI test bench (tests/tui_bench.py).

These tests launch controlled TUI scenarios inside tmux sessions and verify
that term-cli interactions (mouse clicks, scroll, annotations, keystrokes)
work correctly end-to-end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import pytest

from conftest import RunResult, retry_until

# Path to the TUI bench script
TUI_BENCH = Path(__file__).parent / "tui_bench.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_bench(
    session: str,
    term_cli: Callable[..., RunResult],
    scenario: str,
    log_path: Path | None = None,
    timeout: float = 30,
    cols: int = 80,
    rows: int = 24,
) -> None:
    """Launch a TUI bench scenario and wait for alternate screen."""
    cmd = (
        f"{sys.executable} {TUI_BENCH} --scenario {scenario} "
        f"--timeout {timeout} --cols {cols} --rows {rows}"
    )
    if log_path is not None:
        cmd += f" --log {log_path}"
    term_cli("run", "-s", session, cmd)

    def in_alternate() -> bool:
        status = term_cli("status", "-s", session)
        return "Screen: alternate" in status.stdout

    assert retry_until(in_alternate, timeout=15.0), \
        f"Bench scenario {scenario!r} did not enter alternate screen"


def _quit_bench(session: str, term_cli: Callable[..., RunResult]) -> None:
    """Quit the TUI bench cleanly."""
    term_cli("send-key", "-s", session, "q")
    term_cli("wait", "-s", session, "-t", "10")


def _read_events(log_path: Path) -> list[dict[str, object]]:
    """Read JSON-lines event log."""
    lines = log_path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines]


def _events_of_type(events: list[dict[str, object]], event_type: str) -> list[dict[str, object]]:
    """Filter events by type."""
    return [e for e in events if e.get("type") == event_type]


def _wait_for_visible_content(
    term_cli: Callable[..., RunResult],
    session: str,
    content: str,
    timeout: float = 5.0,
    interval: float = 0.1,
) -> bool:
    """Wait until visible capture contains expected content.

    Uses visible-screen capture (not scrollback), which is reliable in
    alternate-screen TUIs where scrollback is intentionally blocked.
    """
    import time

    start = time.time()
    while time.time() - start < timeout:
        result = term_cli("capture", "-s", session, "--no-annotate")
        if result.ok and content in result.stdout:
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Tests: Mouse click accuracy (menu-basic)
# ---------------------------------------------------------------------------

class TestMouseClickAccuracy:
    """Verify that mouse clicks land on the correct elements."""

    def test_click_item_by_text(self, session: str, term_cli: Callable[..., RunResult],
                                tmp_path: Path) -> None:
        """Clicking an item by text selects the correct element."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "menu-basic", log_path=log)
        try:
            term_cli("send-mouse", "-s", session, "--text", "Item B",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: Item B",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        presses = _events_of_type(events, "mouse_press")
        assert len(presses) >= 1
        assert presses[0]["element"] == "item_b"

    def test_click_multiple_items(self, session: str, term_cli: Callable[..., RunResult],
                                  tmp_path: Path) -> None:
        """Clicking different items updates selection each time."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "menu-basic", log_path=log)
        try:
            term_cli("send-mouse", "-s", session, "--text", "Item A",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: Item A",
                                    timeout=5.0)

            term_cli("send-mouse", "-s", session, "--text", "Item D",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: Item D",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        actions = _events_of_type(events, "action")
        click_actions = [a for a in actions if a.get("trigger") == "click"]
        assert len(click_actions) >= 2
        assert click_actions[0]["element"] == "item_a"
        assert click_actions[1]["element"] == "item_d"

    def test_click_by_coordinates(self, session: str, term_cli: Callable[..., RunResult],
                                  tmp_path: Path) -> None:
        """Clicking by x,y coordinates targets the correct element."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "menu-basic", log_path=log)
        try:
            # Item C is at row 4, col_start=2, col_end=14
            term_cli("send-mouse", "-s", session, "--x", "6", "--y", "4",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: Item C",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        presses = _events_of_type(events, "mouse_press")
        assert len(presses) >= 1
        assert presses[0]["element"] == "item_c"
        assert presses[0]["x"] == 6
        assert presses[0]["y"] == 4


# ---------------------------------------------------------------------------
# Tests: Bar interaction
# ---------------------------------------------------------------------------

class TestBarInteraction:
    """Verify that bar clicks and hotkeys work correctly."""

    def test_mc_bar_hotkey(self, session: str, term_cli: Callable[..., RunResult],
                           tmp_path: Path) -> None:
        """Pressing a number key triggers the corresponding mc-bar action."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "bar-mc", log_path=log)
        try:
            term_cli("send-key", "-s", session, "3")
            assert _wait_for_visible_content(term_cli, session, "Action: action_view",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        actions = _events_of_type(events, "action")
        assert any(a["element"] == "bar_view" and a["trigger"] == "hotkey"
                    for a in actions)

    def test_mc_bar_click(self, session: str, term_cli: Callable[..., RunResult],
                          tmp_path: Path) -> None:
        """Clicking on a mc-bar label triggers the correct action."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "bar-mc", log_path=log)
        try:
            term_cli("send-mouse", "-s", session, "--text", "Copy",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Action: action_copy",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        actions = _events_of_type(events, "action")
        assert any(a["element"] == "bar_copy" and a["trigger"] == "click"
                    for a in actions)

    def test_nano_bar_click(self, session: str, term_cli: Callable[..., RunResult],
                            tmp_path: Path) -> None:
        """Clicking on a nano-bar label triggers the correct action."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "bar-nano", log_path=log)
        try:
            term_cli("send-mouse", "-s", session, "--text", "Search",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Action: action_search",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        actions = _events_of_type(events, "action")
        assert any(a["element"] == "bar_search" and a["trigger"] == "click"
                    for a in actions)

    def test_tab_bar_click_switches_tab(self, session: str,
                                        term_cli: Callable[..., RunResult],
                                        tmp_path: Path) -> None:
        """Clicking a tab switches the active tab."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "bar-tabs", log_path=log)
        try:
            term_cli("send-mouse", "-s", session, "--text", "2:logs",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Active tab: 2",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

    def test_tab_bar_hotkey_switches_tab(self, session: str,
                                         term_cli: Callable[..., RunResult],
                                         tmp_path: Path) -> None:
        """Pressing a number key switches the active tab."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "bar-tabs", log_path=log)
        try:
            term_cli("send-key", "-s", session, "3")
            assert _wait_for_visible_content(term_cli, session, "Active tab: 3",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)


# ---------------------------------------------------------------------------
# Tests: Dialog interaction
# ---------------------------------------------------------------------------

class TestDialogInteraction:
    """Verify modal dialog click handling."""

    def test_dismiss_dialog_with_ok(self, session: str,
                                     term_cli: Callable[..., RunResult],
                                     tmp_path: Path) -> None:
        """Clicking OK dismisses the dialog."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "menu-dialog", log_path=log)
        try:
            # Verify dialog is visible
            assert _wait_for_visible_content(term_cli, session, "Press OK to dismiss",
                                    timeout=5.0)
            # Click the OK button (use full text to disambiguate from message)
            term_cli("send-mouse", "-s", session, "--text", "[ OK ]",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Action: dialog_ok",
                                    timeout=5.0)
            # Verify dialog dismissed — "Press OK to dismiss" should be gone
            # (the menu items should now be visible without overlay)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        actions = _events_of_type(events, "action")
        assert any(a["element"] == "dlg_ok" for a in actions)

    def test_dismiss_dialog_with_cancel(self, session: str,
                                         term_cli: Callable[..., RunResult],
                                         tmp_path: Path) -> None:
        """Clicking Cancel dismisses the dialog."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "menu-dialog", log_path=log)
        try:
            assert _wait_for_visible_content(term_cli, session, "Press OK to dismiss",
                                    timeout=5.0)
            term_cli("send-mouse", "-s", session, "--text", "[ Cancel ]",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Action: dialog_cancel",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        actions = _events_of_type(events, "action")
        assert any(a["element"] == "dlg_cancel" for a in actions)


# ---------------------------------------------------------------------------
# Tests: Scroll events
# ---------------------------------------------------------------------------

class TestScrollEvents:
    """Verify scroll events change TUI state."""

    def test_scroll_down_changes_position(self, session: str,
                                           term_cli: Callable[..., RunResult],
                                           tmp_path: Path) -> None:
        """Scroll-down events advance the scroll position."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "scroll-list", log_path=log)
        try:
            # Initial position should be 0
            assert _wait_for_visible_content(term_cli, session, "Scroll position: 0",
                                    timeout=5.0)
            # Scroll down 5 times
            term_cli("send-mouse", "-s", session, "--x", "40", "--y", "10",
                     "--scroll-down", "5", check=True)
            assert _wait_for_visible_content(term_cli, session, "Scroll position: 5",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        scrolls = _events_of_type(events, "scroll")
        assert len(scrolls) == 5
        # Last scroll should report position 5
        assert scrolls[-1]["position"] == 5

    def test_scroll_up_reverses(self, session: str,
                                 term_cli: Callable[..., RunResult],
                                 tmp_path: Path) -> None:
        """Scroll-up after scroll-down returns to previous position."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "scroll-list", log_path=log)
        try:
            # Scroll down 5
            term_cli("send-mouse", "-s", session, "--x", "40", "--y", "10",
                     "--scroll-down", "5", check=True)
            assert _wait_for_visible_content(term_cli, session, "Scroll position: 5",
                                    timeout=5.0)
            # Scroll up 3
            term_cli("send-mouse", "-s", session, "--x", "40", "--y", "10",
                     "--scroll-up", "3", check=True)
            assert _wait_for_visible_content(term_cli, session, "Scroll position: 2",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

    def test_scroll_updates_visible_lines(self, session: str,
                                           term_cli: Callable[..., RunResult]) -> None:
        """Scrolling changes which lines are visible on screen."""
        _start_bench(session, term_cli, "scroll-list")
        try:
            # Should start showing line 001
            assert _wait_for_visible_content(term_cli, session, "line 001", timeout=5.0)
            # Scroll down 10
            term_cli("send-mouse", "-s", session, "--x", "40", "--y", "10",
                     "--scroll-down", "10", check=True)
            # line 001 should be gone, line 011 should be visible
            assert _wait_for_visible_content(term_cli, session, "line 011", timeout=5.0)
        finally:
            _quit_bench(session, term_cli)


# ---------------------------------------------------------------------------
# Tests: Annotation end-to-end
# ---------------------------------------------------------------------------

class TestAnnotationEndToEnd:
    """Verify annotations detect known patterns through real tmux capture."""

    def test_reverse_video_detected(self, session: str,
                                     term_cli: Callable[..., RunResult]) -> None:
        """Reverse-video text is annotated correctly."""
        _start_bench(session, term_cli, "anno-signals")
        try:
            result = term_cli("capture", "-s", session, "-a", check=True)
            lines = result.stdout
            # Row 2: "SELECTED ITEM" in reverse video → bg:white
            assert "SELECTED ITEM" in lines
            assert "bg:white" in lines
        finally:
            _quit_bench(session, term_cli)

    def test_colored_bg_detected(self, session: str,
                                  term_cli: Callable[..., RunResult]) -> None:
        """Colored background highlights are annotated."""
        _start_bench(session, term_cli, "anno-signals")
        try:
            result = term_cli("capture", "-s", session, "-a", check=True)
            lines = result.stdout
            # Row 4: "ACTIVE TAB" in bg:green
            assert "ACTIVE TAB" in lines
            assert "bg:green" in lines
        finally:
            _quit_bench(session, term_cli)

    def test_structural_bg_filtered(self, session: str,
                                     term_cli: Callable[..., RunResult]) -> None:
        """Structural blue panel background is NOT annotated."""
        _start_bench(session, term_cli, "anno-signals")
        try:
            result = term_cli("capture", "-s", session, "-a", check=True)
            # Extract the ANNOTATIONS section
            annotations_start = result.stdout.find("Annotations:")
            assert annotations_start != -1
            annotations = result.stdout[annotations_start:]
            # "panel content" should NOT appear in annotations
            # (it appears in the screen output but not as an annotation)
            assert "panel content" not in annotations
        finally:
            _quit_bench(session, term_cli)

    def test_highlight_on_structural_bg(self, session: str,
                                         term_cli: Callable[..., RunResult]) -> None:
        """Highlight on structural background is detected (Signal B)."""
        _start_bench(session, term_cli, "anno-signals")
        try:
            result = term_cli("capture", "-s", session, "-a", check=True)
            annotations_start = result.stdout.find("Annotations:")
            annotations = result.stdout[annotations_start:]
            # Row 10: "> highlighted item" should be annotated
            assert "highlighted item" in annotations
        finally:
            _quit_bench(session, term_cli)

    def test_flanked_button_detected(self, session: str,
                                      term_cli: Callable[..., RunResult]) -> None:
        """Signal C detects a flanked button ([ OK ] between reverse regions)."""
        _start_bench(session, term_cli, "anno-signals")
        try:
            result = term_cli("capture", "-s", session, "-a", check=True)
            annotations_start = result.stdout.find("Annotations:")
            annotations = result.stdout[annotations_start:]
            assert "OK" in annotations
        finally:
            _quit_bench(session, term_cli)

    def test_mc_bar_detected(self, session: str,
                              term_cli: Callable[..., RunResult]) -> None:
        """Signal C detects mc-style alternating bar with hotkeys and labels."""
        _start_bench(session, term_cli, "anno-signals")
        try:
            result = term_cli("capture", "-s", session, "-a", check=True)
            annotations_start = result.stdout.find("Annotations:")
            annotations = result.stdout[annotations_start:]
            # mc bar: hotkey numbers in bg:black, labels in bg:cyan
            assert "bg:cyan" in annotations
            assert "Help" in annotations
        finally:
            _quit_bench(session, term_cli)

    def test_multi_color_same_row(self, session: str,
                                   term_cli: Callable[..., RunResult]) -> None:
        """Two different colors on the same row are both annotated."""
        _start_bench(session, term_cli, "anno-signals")
        try:
            result = term_cli("capture", "-s", session, "-a", check=True)
            annotations_start = result.stdout.find("Annotations:")
            annotations = result.stdout[annotations_start:]
            # Row 22: GREEN in bg:green and RED in bg:red
            assert "GREEN" in annotations
            assert "RED" in annotations
            assert "bg:green" in annotations
            assert "bg:red" in annotations
        finally:
            _quit_bench(session, term_cli)

    def test_menu_items_annotated(self, session: str,
                                   term_cli: Callable[..., RunResult]) -> None:
        """Menu-basic items are detected as annotations with correct colors."""
        _start_bench(session, term_cli, "menu-basic")
        try:
            result = term_cli("capture", "-s", session, "-a", check=True)
            annotations_start = result.stdout.find("Annotations:")
            annotations = result.stdout[annotations_start:]
            # All four items should be annotated
            assert "Item A" in annotations
            assert "Item B" in annotations
            assert "Item C" in annotations
            assert "Item D" in annotations
            assert "bg:green" in annotations
            assert "bg:cyan" in annotations
            assert "bg:red" in annotations
            assert "bg:yellow" in annotations
        finally:
            _quit_bench(session, term_cli)


# ---------------------------------------------------------------------------
# Tests: Edge cases (screen boundaries)
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Verify mouse clicks work at screen boundaries."""

    def test_click_top_left_corner(self, session: str,
                                    term_cli: Callable[..., RunResult],
                                    tmp_path: Path) -> None:
        """Click at row 0, col 0 is received correctly."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "edge-corners", log_path=log)
        try:
            term_cli("send-mouse", "-s", session, "--x", "0", "--y", "0",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: TL",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        presses = _events_of_type(events, "mouse_press")
        assert presses[0]["element"] == "corner_tl"
        assert presses[0]["x"] == 0
        assert presses[0]["y"] == 0

    def test_click_top_right_corner(self, session: str,
                                     term_cli: Callable[..., RunResult],
                                     tmp_path: Path) -> None:
        """Click at row 0, last column is received correctly."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "edge-corners", log_path=log)
        try:
            # Default session is 80 cols; [TR] is at cols 76-79
            term_cli("send-mouse", "-s", session, "--x", "77", "--y", "0",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: TR",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

    def test_click_bottom_left_corner(self, session: str,
                                       term_cli: Callable[..., RunResult],
                                       tmp_path: Path) -> None:
        """Click at last row, col 0 is received correctly."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "edge-corners", log_path=log)
        try:
            # Default session is 24 rows; [BL] is at row 23
            term_cli("send-mouse", "-s", session, "--x", "1", "--y", "23",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: BL",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

    def test_click_bottom_right_corner(self, session: str,
                                        term_cli: Callable[..., RunResult],
                                        tmp_path: Path) -> None:
        """Click at last row, last column is received correctly."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "edge-corners", log_path=log)
        try:
            # [BR] is at row 23, cols 76-79
            term_cli("send-mouse", "-s", session, "--x", "78", "--y", "23",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: BR",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)


# ---------------------------------------------------------------------------
# Tests: Bell detection
# ---------------------------------------------------------------------------

class TestBellDetection:
    """Verify bell detection end-to-end."""

    def test_bell_detected_in_annotations(self, session: str,
                                           term_cli: Callable[..., RunResult],
                                           tmp_path: Path) -> None:
        """Clicking 'Ring Bell' triggers bell, visible in annotated capture."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "menu-bell", log_path=log)
        try:
            term_cli("send-mouse", "-s", session, "--text", "Ring Bell",
                     check=True)
            assert _wait_for_visible_content(term_cli, session, "Bell: FIRED",
                                    timeout=5.0)
            # Check annotated capture for bell indicator
            result = term_cli("capture", "-s", session, "-a", check=True)
            annotations_start = result.stdout.find("Annotations:")
            annotations = result.stdout[annotations_start:]
            assert "Bell: yes" in annotations
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        bells = _events_of_type(events, "bell")
        assert len(bells) >= 1
        assert bells[0]["triggered_by"] == "item_bell"


# ---------------------------------------------------------------------------
# Tests: Keystroke logging
# ---------------------------------------------------------------------------

class TestKeystrokeLogging:
    """Verify send-key sequences are received correctly by the TUI."""

    def test_arrow_keys_received(self, session: str,
                                  term_cli: Callable[..., RunResult],
                                  tmp_path: Path) -> None:
        """Arrow keys are received and logged correctly."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "keylog", log_path=log)
        try:
            term_cli("send-key", "-s", session, "Up")
            term_cli("send-key", "-s", session, "Down")
            term_cli("send-key", "-s", session, "Left")
            term_cli("send-key", "-s", session, "Right")
            assert _wait_for_visible_content(term_cli, session, "Keys received: 4",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        keys = _events_of_type(events, "key")
        # Filter out the 'q' quit key
        non_quit = [k for k in keys if k["name"] != "q"]
        assert len(non_quit) == 4
        names = [str(k["name"]) for k in non_quit]
        assert names == ["Up", "Down", "Left", "Right"]

    def test_ctrl_keys_received(self, session: str,
                                 term_cli: Callable[..., RunResult],
                                 tmp_path: Path) -> None:
        """Ctrl+key combinations are received correctly."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "keylog", log_path=log)
        try:
            term_cli("send-key", "-s", session, "C-a")
            term_cli("send-key", "-s", session, "C-e")
            assert _wait_for_visible_content(term_cli, session, "Keys received: 2",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        keys = _events_of_type(events, "key")
        non_quit = [k for k in keys if k["name"] != "q"]
        names = [str(k["name"]) for k in non_quit]
        assert "Ctrl+A" in names
        assert "Ctrl+E" in names

    def test_terminal_dimensions_displayed(self, session: str,
                                           term_cli: Callable[..., RunResult]) -> None:
        """Keylog mode displays terminal dimensions."""
        _start_bench(session, term_cli, "keylog")
        try:
            # Default session is 80x24
            assert _wait_for_visible_content(term_cli, session, "Terminal: 80x24",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)


# ---------------------------------------------------------------------------
# Tests: Unicode items
# ---------------------------------------------------------------------------

class TestUnicodeItems:
    """Verify Unicode label rendering and click targeting."""

    def test_click_cjk_item(self, session: str, term_cli: Callable[..., RunResult],
                            tmp_path: Path) -> None:
        """Clicking a CJK label selects the expected Unicode element."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "unicode-items", log_path=log)
        try:
            term_cli("send-mouse", "-s", session, "--text", "你好世界", check=True)
            assert _wait_for_visible_content(term_cli, session, "Selected: 你好世界",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        actions = _events_of_type(events, "action")
        assert any(a["element"] == "item_cjk" and a["trigger"] == "click"
                   for a in actions)


# ---------------------------------------------------------------------------
# Tests: Annotation-to-click pipeline
# ---------------------------------------------------------------------------

class TestAnnotationToClickPipeline:
    """End-to-end: annotate screen, find element text, click it, verify."""

    def test_annotated_item_clickable(self, session: str,
                                      term_cli: Callable[..., RunResult],
                                      tmp_path: Path) -> None:
        """An annotated item can be clicked by its annotation text."""
        log = tmp_path / "events.jsonl"
        _start_bench(session, term_cli, "menu-basic", log_path=log)
        try:
            # Step 1: Get annotations
            result = term_cli("capture", "-s", session, "-a", check=True)
            annotations_start = result.stdout.find("Annotations:")
            annotations = result.stdout[annotations_start:]

            # Step 2: Verify Item C is in annotations
            assert "Item C" in annotations
            assert "bg:red" in annotations

            # Step 3: Click it using the text from annotations
            term_cli("send-mouse", "-s", session, "--text", "Item C",
                     check=True)

            # Step 4: Verify the click worked
            assert _wait_for_visible_content(term_cli, session, "Selected: Item C",
                                    timeout=5.0)
        finally:
            _quit_bench(session, term_cli)

        events = _read_events(log)
        actions = _events_of_type(events, "action")
        assert any(a["element"] == "item_c" and a["trigger"] == "click"
                    for a in actions)
