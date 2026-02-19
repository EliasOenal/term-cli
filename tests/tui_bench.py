#!/usr/bin/env python3
"""TUI test bench — controlled TUI layouts for verifying term-cli interactions.

A stdlib-only Python script that renders deterministic TUI layouts inside a
tmux session.  Each ``--scenario`` produces a known screen with known element
positions, colors, and interactive behaviors.  On exit the bench writes a
JSON-lines event log so tests can verify that mouse clicks, scroll events,
and keystrokes were received and dispatched to the correct elements.

Usage::

    python tests/tui_bench.py --scenario menu-basic --log /tmp/events.jsonl
    python tests/tui_bench.py --scenario keylog --timeout 30

Scenarios
---------
menu-basic      4 clickable items + mc-style bar + status display
menu-dialog     menu-basic with a modal OK/Cancel dialog overlay
menu-bell       menu-basic where one item triggers BEL
bar-mc          full-width mc-style alternating bar with number hotkeys
bar-nano        two-row nano-style bar with Ctrl hotkeys
bar-tabs        tmux-style tab bar with one highlighted tab
scroll-list     scrollable 100-line list with position indicator
anno-signals    all annotation patterns for end-to-end capture testing
unicode-items   CJK / wide-char menu items for click targeting
edge-corners    clickable elements at all four screen corners
keylog          blank screen that logs every keystroke received
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import curses
import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Element:
    """A hit-testable region on screen."""

    id: str
    row: int          # 0-based
    col_start: int    # 0-based inclusive
    col_end: int      # 0-based exclusive
    text: str         # display text
    color_pair: int   # curses color pair index
    action: str = ""  # action name triggered on click/hotkey

    def contains(self, x: int, y: int) -> bool:
        return y == self.row and self.col_start <= x < self.col_end


@dataclass
class BarItem:
    """One item in a bottom bar."""

    id: str
    label: str
    hotkey_display: str   # e.g. "1", "^G", "F1"
    hotkey_label: str     # label for the event log
    action: str


@dataclass
class BarDef:
    """Definition of a bottom bar."""

    style: str                         # "mc", "nano", "tabs"
    items: list[BarItem] = field(default_factory=list)
    row_start: int = 0                 # set during layout
    hotkey_color_pair: int = 0         # curses pair for hotkey portion
    label_color_pair: int = 0          # curses pair for label portion
    selected_color_pair: int = 0       # for tabs: highlighted tab


@dataclass
class DialogDef:
    """A modal dialog overlay."""

    title: str
    message: str
    buttons: list[Element] = field(default_factory=list)
    row_start: int = 0
    col_start: int = 0
    width: int = 0
    height: int = 0
    visible: bool = False


@dataclass
class ScenarioState:
    """Mutable state for a running scenario."""

    selected: str = ""
    last_event: str = ""
    action: str = ""
    scroll_pos: int = 0
    dialog_visible: bool = False
    tab_selected: int = 0
    running: bool = True
    bell_fired: bool = False


# ---------------------------------------------------------------------------
# Event logging
# ---------------------------------------------------------------------------

class EventLogger:
    """Collects events and writes them as JSON lines on flush."""

    def __init__(self, path: str | None) -> None:
        self._path = path
        self._events: list[dict[str, object]] = []
        self._counts: dict[str, int] = {
            "mouse_press": 0,
            "mouse_release": 0,
            "scroll": 0,
            "key": 0,
            "action": 0,
            "bell": 0,
        }

    def log(self, event: dict[str, object]) -> None:
        etype = str(event.get("type", ""))
        if etype in self._counts:
            self._counts[etype] += 1
        self._events.append(event)

    def flush(self) -> None:
        summary: dict[str, object] = {"type": "summary"}
        summary.update(self._counts)
        self._events.append(summary)
        text = "\n".join(json.dumps(e) for e in self._events) + "\n"
        if self._path:
            with open(self._path, "w") as f:
                f.write(text)
        else:
            # Write to original stdout (saved before curses takes over)
            _orig_stdout.write(text)
            _orig_stdout.flush()

# We save original stdout before curses redirects it.
_orig_stdout = sys.stdout


# ---------------------------------------------------------------------------
# SGR mouse parser
# ---------------------------------------------------------------------------

# SGR extended mouse: \x1b[<button;x;y{M|m}
# button codes: 0=left, 1=middle, 2=right, 64=scroll-up, 65=scroll-down
# M=press, m=release
_SGR_MOUSE_RE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")

_BUTTON_NAMES: dict[int, str] = {
    0: "left",
    1: "middle",
    2: "right",
    64: "scroll_up",
    65: "scroll_down",
}


@dataclass
class MouseEvent:
    """Parsed SGR mouse event."""

    button: str       # "left", "right", "scroll_up", "scroll_down"
    button_code: int   # raw SGR code
    x: int            # 0-based column
    y: int            # 0-based row
    pressed: bool     # True=press, False=release


def parse_mouse_events(buf: bytes) -> tuple[list[MouseEvent], bytes]:
    """Extract all complete SGR mouse events from *buf*.

    Returns parsed events and the remaining unconsumed bytes.
    """
    events: list[MouseEvent] = []
    last_end = 0
    for m in _SGR_MOUSE_RE.finditer(buf):
        code = int(m.group(1))
        # SGR coordinates are 1-based; convert to 0-based
        x = int(m.group(2)) - 1
        y = int(m.group(3)) - 1
        pressed = m.group(4) == b"M"
        btn = _BUTTON_NAMES.get(code, f"unknown_{code}")
        events.append(MouseEvent(button=btn, button_code=code, x=x, y=y, pressed=pressed))
        last_end = m.end()
    remainder = buf[last_end:] if last_end else buf
    return events, remainder


# ---------------------------------------------------------------------------
# Color pair registry
# ---------------------------------------------------------------------------

# We pre-define a fixed set of color pairs so scenarios can reference them by
# name.  curses.init_pair() must be called after curses.initscr().

COLOR_PAIRS: dict[str, int] = {}

_PAIR_DEFS: list[tuple[str, int, int]] = [
    # (name, fg_curses_color, bg_curses_color)
    ("default",        curses.COLOR_WHITE,  curses.COLOR_BLACK),
    ("title",          curses.COLOR_BLACK,  curses.COLOR_WHITE),    # reverse
    ("item_green",     curses.COLOR_BLACK,  curses.COLOR_GREEN),
    ("item_cyan",      curses.COLOR_BLACK,  curses.COLOR_CYAN),
    ("item_red",       curses.COLOR_WHITE,  curses.COLOR_RED),
    ("item_yellow",    curses.COLOR_BLACK,  curses.COLOR_YELLOW),
    ("item_magenta",   curses.COLOR_WHITE,  curses.COLOR_MAGENTA),
    ("item_blue",      curses.COLOR_WHITE,  curses.COLOR_BLUE),
    ("bar_hotkey",     curses.COLOR_WHITE,  curses.COLOR_BLACK),    # mc number
    ("bar_label",      curses.COLOR_BLACK,  curses.COLOR_CYAN),     # mc label
    ("bar_nano_key",   curses.COLOR_BLACK,  curses.COLOR_WHITE),    # nano ^X
    ("bar_nano_label", curses.COLOR_WHITE,  curses.COLOR_BLACK),    # nano label
    ("tab_normal",     curses.COLOR_WHITE,  curses.COLOR_BLACK),
    ("tab_selected",   curses.COLOR_BLACK,  curses.COLOR_GREEN),
    ("dialog_border",  curses.COLOR_WHITE,  curses.COLOR_BLUE),
    ("dialog_body",    curses.COLOR_WHITE,  curses.COLOR_BLUE),
    ("dialog_button",  curses.COLOR_BLACK,  curses.COLOR_WHITE),
    ("status",         curses.COLOR_GREEN,  curses.COLOR_BLACK),
    ("structural_blue", curses.COLOR_WHITE, curses.COLOR_BLUE),
    ("highlight_on_blue", curses.COLOR_BLACK, curses.COLOR_WHITE),
    ("button_flanked", curses.COLOR_BLACK,  curses.COLOR_WHITE),    # Signal C
]


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    for i, (name, fg, bg) in enumerate(_PAIR_DEFS, start=1):
        curses.init_pair(i, fg, bg)
        COLOR_PAIRS[name] = i


def cpair(name: str) -> int:
    """Return curses.color_pair(n) for a named pair."""
    return curses.color_pair(COLOR_PAIRS[name])


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def safe_addstr(win: curses.window, row: int, col: int, text: str,
                attr: int = 0) -> None:
    """addstr that silently ignores writes outside the window."""
    max_y, max_x = win.getmaxyx()
    if row < 0 or row >= max_y or col >= max_x:
        return
    # Truncate text to fit within the window
    available = max_x - col
    if available <= 0:
        return
    text = text[:available]
    try:
        win.addstr(row, col, text, attr)
    except curses.error:
        # Writing to the bottom-right corner raises an error after the
        # character is actually written — ignore it.
        pass


def draw_hline(win: curses.window, row: int, col: int, width: int,
               attr: int = 0) -> None:
    """Draw a horizontal line of dashes."""
    safe_addstr(win, row, col, "\u2500" * width, attr)


def fill_row(win: curses.window, row: int, attr: int) -> None:
    """Fill an entire row with spaces using the given attribute."""
    _, max_x = win.getmaxyx()
    safe_addstr(win, row, 0, " " * max_x, attr)


# ---------------------------------------------------------------------------
# Element hit-testing
# ---------------------------------------------------------------------------

def hit_test(elements: list[Element], x: int, y: int) -> Element | None:
    """Find the element at (x, y), or None."""
    for el in elements:
        if el.contains(x, y):
            return el
    return None


# ---------------------------------------------------------------------------
# Bar rendering and element generation
# ---------------------------------------------------------------------------

def build_bar_elements(bar: BarDef, max_x: int) -> list[Element]:
    """Build Element list from a BarDef for hit-testing."""
    elements: list[Element] = []
    if bar.style == "mc":
        col = 0
        for item in bar.items:
            hotkey_w = len(item.hotkey_display)
            label_w = max(len(item.label), 6)
            # The whole item (hotkey + label) is one clickable element
            el = Element(
                id=item.id,
                row=bar.row_start,
                col_start=col,
                col_end=col + hotkey_w + label_w,
                text=item.hotkey_display + item.label,
                color_pair=bar.label_color_pair,
                action=item.action,
            )
            elements.append(el)
            col += hotkey_w + label_w
    elif bar.style == "nano":
        for row_off in range(2):
            col = 0
            row = bar.row_start + row_off
            per_row = len(bar.items) // 2
            start = row_off * per_row
            end = start + per_row
            for item in bar.items[start:end]:
                key_w = len(item.hotkey_display)
                label_w = max(len(item.label) + 1, 8)  # pad label
                el = Element(
                    id=item.id,
                    row=row,
                    col_start=col,
                    col_end=col + key_w + label_w,
                    text=item.hotkey_display + " " + item.label,
                    color_pair=bar.label_color_pair,
                    action=item.action,
                )
                elements.append(el)
                col += key_w + label_w
    elif bar.style == "tabs":
        col = 0
        for i, item in enumerate(bar.items):
            tab_text = f"[{item.label}]"
            w = len(tab_text) + 1  # +1 for spacing
            el = Element(
                id=item.id,
                row=bar.row_start,
                col_start=col,
                col_end=col + w,
                text=tab_text,
                color_pair=bar.selected_color_pair if i == 0 else bar.hotkey_color_pair,
                action=item.action,
            )
            elements.append(el)
            col += w
    return elements


def draw_bar(win: curses.window, bar: BarDef, state: ScenarioState) -> None:
    """Render a bar onto the window."""
    max_y, max_x = win.getmaxyx()
    if bar.style == "mc":
        col = 0
        fill_row(win, bar.row_start, cpair("bar_label"))
        for item in bar.items:
            hotkey_w = len(item.hotkey_display)
            label_w = max(len(item.label), 6)
            safe_addstr(win, bar.row_start, col, item.hotkey_display,
                        cpair("bar_hotkey"))
            safe_addstr(win, bar.row_start, col + hotkey_w,
                        f"{item.label:<{label_w}s}", cpair("bar_label"))
            col += hotkey_w + label_w
    elif bar.style == "nano":
        for row_off in range(2):
            row = bar.row_start + row_off
            fill_row(win, row, cpair("bar_nano_label"))
            col = 0
            per_row = len(bar.items) // 2
            start = row_off * per_row
            end = start + per_row
            for item in bar.items[start:end]:
                key_w = len(item.hotkey_display)
                label_w = max(len(item.label) + 1, 8)
                safe_addstr(win, row, col, item.hotkey_display,
                            cpair("bar_nano_key"))
                safe_addstr(win, row, col + key_w,
                            f" {item.label:<{label_w - 1}s}",
                            cpair("bar_nano_label"))
                col += key_w + label_w
    elif bar.style == "tabs":
        fill_row(win, bar.row_start, cpair("tab_normal"))
        col = 0
        for i, item in enumerate(bar.items):
            tab_text = f"[{item.label}]"
            w = len(tab_text) + 1
            pair = "tab_selected" if i == state.tab_selected else "tab_normal"
            safe_addstr(win, bar.row_start, col, tab_text, cpair(pair))
            col += w


# ---------------------------------------------------------------------------
# Dialog rendering
# ---------------------------------------------------------------------------

def draw_dialog(win: curses.window, dlg: DialogDef) -> None:
    """Render a modal dialog box."""
    if not dlg.visible:
        return
    r, c, w, h = dlg.row_start, dlg.col_start, dlg.width, dlg.height
    border = cpair("dialog_border")
    body = cpair("dialog_body")
    # Top border
    safe_addstr(win, r, c, "\u250c" + "\u2500" * (w - 2) + "\u2510", border)
    # Body rows
    for dy in range(1, h - 1):
        safe_addstr(win, r + dy, c, "\u2502" + " " * (w - 2) + "\u2502", body)
    # Bottom border
    safe_addstr(win, r + h - 1, c, "\u2514" + "\u2500" * (w - 2) + "\u2518", border)
    # Title
    title = f" {dlg.title} "
    tx = c + (w - len(title)) // 2
    safe_addstr(win, r, tx, title, border | curses.A_BOLD)
    # Message
    safe_addstr(win, r + 2, c + 2, dlg.message, body)
    # Buttons
    for btn in dlg.buttons:
        safe_addstr(win, btn.row, btn.col_start, btn.text,
                    cpair("dialog_button"))


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, str] = {
    "menu-basic": "4 clickable items + mc-style bar + status display",
    "menu-dialog": "menu-basic with modal OK/Cancel dialog",
    "menu-bell": "menu-basic where one item triggers BEL",
    "bar-mc": "full-width mc-style bar with number hotkeys",
    "bar-nano": "two-row nano-style bar with Ctrl hotkeys",
    "bar-tabs": "tmux-style tab bar with highlighted tab",
    "scroll-list": "scrollable 100-line list with position indicator",
    "anno-signals": "annotation patterns for end-to-end capture testing",
    "unicode-items": "CJK / wide-char menu items",
    "edge-corners": "clickable elements at screen corners",
    "keylog": "blank screen logging every keystroke",
}


# --- menu-basic -----------------------------------------------------------

def _menu_elements() -> tuple[list[Element], BarDef]:
    items = [
        Element("item_a", row=2, col_start=2, col_end=14,
                text="[ Item A ]", color_pair=COLOR_PAIRS["item_green"],
                action="select_a"),
        Element("item_b", row=3, col_start=2, col_end=14,
                text="[ Item B ]", color_pair=COLOR_PAIRS["item_cyan"],
                action="select_b"),
        Element("item_c", row=4, col_start=2, col_end=14,
                text="[ Item C ]", color_pair=COLOR_PAIRS["item_red"],
                action="select_c"),
        Element("item_d", row=5, col_start=2, col_end=14,
                text="[ Item D ]", color_pair=COLOR_PAIRS["item_yellow"],
                action="select_d"),
    ]
    bar = BarDef(
        style="mc",
        items=[
            BarItem("bar_help", "Help", "1", "1", "action_help"),
            BarItem("bar_menu", "Menu", "2", "2", "action_menu"),
            BarItem("bar_view", "View", "3", "3", "action_view"),
            BarItem("bar_edit", "Edit", "4", "4", "action_edit"),
            BarItem("bar_copy", "Copy", "5", "5", "action_copy"),
            BarItem("bar_quit", "Quit", "6", "6", "action_quit"),
        ],
    )
    return items, bar


def _draw_menu_status(win: curses.window, state: ScenarioState) -> None:
    attr = cpair("status")
    safe_addstr(win, 7, 2, f"Selected: {state.selected or '(none)':30s}", attr)
    safe_addstr(win, 8, 2, f"Action: {state.action or '(none)':30s}", attr)
    safe_addstr(win, 9, 2, f"Last event: {state.last_event:40s}", attr)


def _draw_menu_base(win: curses.window, elements: list[Element],
                    state: ScenarioState) -> None:
    win.erase()
    max_y, max_x = win.getmaxyx()
    # Title
    fill_row(win, 0, cpair("title"))
    safe_addstr(win, 0, 2, "Menu Test Bench", cpair("title") | curses.A_BOLD)
    # Items
    for el in elements:
        safe_addstr(win, el.row, el.col_start, f"{el.text:12s}",
                    curses.color_pair(el.color_pair))
    # Status
    _draw_menu_status(win, state)
    # Footer hint
    safe_addstr(win, max_y - 2, 2, "[q] quit", cpair("default"))


def scenario_menu_basic(win: curses.window, logger: EventLogger,
                        timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    elements, bar = _menu_elements()
    bar.row_start = max_y - 1
    bar.hotkey_color_pair = COLOR_PAIRS["bar_hotkey"]
    bar.label_color_pair = COLOR_PAIRS["bar_label"]
    bar_elements = build_bar_elements(bar, max_x)
    all_elements = elements + bar_elements
    state = ScenarioState()

    # Map bar hotkeys (number keys) to bar elements
    hotkey_map: dict[str, Element] = {}
    for bi, el in zip(bar.items, bar_elements):
        hotkey_map[bi.hotkey_display] = el

    def redraw() -> None:
        _draw_menu_base(win, elements, state)
        draw_bar(win, bar, state)
        win.refresh()

    _run_event_loop(win, all_elements, state, logger, redraw,
                    hotkey_map=hotkey_map, timeout=timeout)


# --- menu-dialog ----------------------------------------------------------

def scenario_menu_dialog(win: curses.window, logger: EventLogger,
                         timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    elements, bar = _menu_elements()
    bar.row_start = max_y - 1
    bar.hotkey_color_pair = COLOR_PAIRS["bar_hotkey"]
    bar.label_color_pair = COLOR_PAIRS["bar_label"]
    bar_elements = build_bar_elements(bar, max_x)
    state = ScenarioState()

    # Dialog
    dw, dh = 30, 6
    dr = (max_y - dh) // 2
    dc = (max_x - dw) // 2
    ok_btn = Element("dlg_ok", row=dr + 3, col_start=dc + 8, col_end=dc + 14,
                     text="[ OK ]", color_pair=COLOR_PAIRS["dialog_button"],
                     action="dialog_ok")
    cancel_btn = Element("dlg_cancel", row=dr + 3, col_start=dc + 16,
                         col_end=dc + 26, text="[ Cancel ]",
                         color_pair=COLOR_PAIRS["dialog_button"],
                         action="dialog_cancel")
    dlg = DialogDef(
        title="Info",
        message="Press OK to dismiss",
        buttons=[ok_btn, cancel_btn],
        row_start=dr, col_start=dc, width=dw, height=dh,
        visible=True,
    )
    state.dialog_visible = True
    all_elements = elements + bar_elements + [ok_btn, cancel_btn]

    hotkey_map: dict[str, Element] = {}
    for bi, el in zip(bar.items, bar_elements):
        hotkey_map[bi.hotkey_display] = el

    def redraw() -> None:
        _draw_menu_base(win, elements, state)
        draw_bar(win, bar, state)
        dlg.visible = state.dialog_visible
        draw_dialog(win, dlg)
        win.refresh()

    def on_action(action: str) -> None:
        if action in ("dialog_ok", "dialog_cancel"):
            state.dialog_visible = False
            state.action = action

    _run_event_loop(win, all_elements, state, logger, redraw,
                    hotkey_map=hotkey_map, on_action=on_action,
                    timeout=timeout)


# --- menu-bell ------------------------------------------------------------

def scenario_menu_bell(win: curses.window, logger: EventLogger,
                       timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    elements, bar = _menu_elements()
    # Replace item_d with a bell trigger
    elements[3] = Element(
        "item_bell", row=5, col_start=2, col_end=16,
        text="[ Ring Bell ]", color_pair=COLOR_PAIRS["item_yellow"],
        action="ring_bell",
    )
    bar.row_start = max_y - 1
    bar.hotkey_color_pair = COLOR_PAIRS["bar_hotkey"]
    bar.label_color_pair = COLOR_PAIRS["bar_label"]
    bar_elements = build_bar_elements(bar, max_x)
    all_elements = elements + bar_elements
    state = ScenarioState()

    hotkey_map: dict[str, Element] = {}
    for bi, el in zip(bar.items, bar_elements):
        hotkey_map[bi.hotkey_display] = el

    def on_action(action: str) -> None:
        if action == "ring_bell":
            curses.beep()
            state.bell_fired = True
            logger.log({"type": "bell", "triggered_by": "item_bell"})

    def redraw() -> None:
        _draw_menu_base(win, elements, state)
        bell_status = "FIRED" if state.bell_fired else "no"
        safe_addstr(win, 11, 2, f"Bell: {bell_status:10s}", cpair("status"))
        draw_bar(win, bar, state)
        win.refresh()

    _run_event_loop(win, all_elements, state, logger, redraw,
                    hotkey_map=hotkey_map, on_action=on_action,
                    timeout=timeout)


# --- bar-mc ---------------------------------------------------------------

def scenario_bar_mc(win: curses.window, logger: EventLogger,
                    timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    bar = BarDef(
        style="mc",
        items=[
            BarItem("bar_help",  "Help",  "1",  "1",  "action_help"),
            BarItem("bar_menu",  "Menu",  "2",  "2",  "action_menu"),
            BarItem("bar_view",  "View",  "3",  "3",  "action_view"),
            BarItem("bar_edit",  "Edit",  "4",  "4",  "action_edit"),
            BarItem("bar_copy",  "Copy",  "5",  "5",  "action_copy"),
            BarItem("bar_move",  "RenMov","6",  "6",  "action_move"),
            BarItem("bar_mkdir", "Mkdir", "7",  "7",  "action_mkdir"),
            BarItem("bar_del",   "Del",   "8",  "8",  "action_del"),
            BarItem("bar_pull",  "PullDn","9",  "9",  "action_pull"),
            BarItem("bar_quit",  "Quit",  "10", "10", "action_quit"),
        ],
        row_start=max_y - 1,
        hotkey_color_pair=COLOR_PAIRS["bar_hotkey"],
        label_color_pair=COLOR_PAIRS["bar_label"],
    )
    bar_elements = build_bar_elements(bar, max_x)
    state = ScenarioState()

    # Map number hotkeys
    hotkey_map: dict[str, Element] = {}
    for bi, el in zip(bar.items, bar_elements):
        hotkey_map[bi.hotkey_display] = el

    def redraw() -> None:
        win.erase()
        fill_row(win, 0, cpair("title"))
        safe_addstr(win, 0, 2, "Bar (mc-style) Test Bench",
                    cpair("title") | curses.A_BOLD)
        safe_addstr(win, 2, 2, f"Action: {state.action or '(none)':30s}",
                    cpair("status"))
        safe_addstr(win, 3, 2, f"Last event: {state.last_event:40s}",
                    cpair("status"))
        safe_addstr(win, max_y - 2, 2, "[q] quit", cpair("default"))
        draw_bar(win, bar, state)
        win.refresh()

    _run_event_loop(win, bar_elements, state, logger, redraw,
                    hotkey_map=hotkey_map, timeout=timeout)


# --- bar-nano -------------------------------------------------------------

def scenario_bar_nano(win: curses.window, logger: EventLogger,
                      timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    # nano has 12 items across 2 rows
    bar = BarDef(
        style="nano",
        items=[
            # Row 1 (first 6)
            BarItem("bar_help",    "Help",    "^G", "ctrl_g", "action_help"),
            BarItem("bar_write",   "Write",   "^O", "ctrl_o", "action_write"),
            BarItem("bar_search",  "Search",  "^W", "ctrl_w", "action_search"),
            BarItem("bar_cut",     "Cut",     "^K", "ctrl_k", "action_cut"),
            BarItem("bar_paste",   "Paste",   "^U", "ctrl_u", "action_paste"),
            BarItem("bar_justify", "Justify", "^J", "ctrl_j", "action_justify"),
            # Row 2 (last 6)
            BarItem("bar_exit",    "Exit",    "^X", "ctrl_x", "action_exit"),
            BarItem("bar_read",    "Read",    "^R", "ctrl_r", "action_read"),
            BarItem("bar_replace", "Replace", "^\\","ctrl_\\","action_replace"),
            BarItem("bar_exec",    "Execute", "^T", "ctrl_t", "action_exec"),
            BarItem("bar_loc",     "Location","^C", "ctrl_c_nano", "action_loc"),
            BarItem("bar_goto",    "Go To",   "^_", "ctrl__", "action_goto"),
        ],
        row_start=max_y - 2,
        hotkey_color_pair=COLOR_PAIRS["bar_nano_key"],
        label_color_pair=COLOR_PAIRS["bar_nano_label"],
    )
    bar_elements = build_bar_elements(bar, max_x)
    state = ScenarioState()

    # Map Ctrl hotkeys: curses represents Ctrl+X as chr(24) etc.
    ctrl_mapping = {
        7: "bar_help",      # ^G
        15: "bar_write",    # ^O
        23: "bar_search",   # ^W
        11: "bar_cut",      # ^K
        21: "bar_paste",    # ^U
        10: "bar_justify",  # ^J
        24: "bar_exit",     # ^X
        18: "bar_read",     # ^R
        28: "bar_replace",  # ^\
        20: "bar_exec",     # ^T
        # ^C (3) conflicts with interrupt — skip for safety
        31: "bar_goto",     # ^_
    }
    el_by_id = {el.id: el for el in bar_elements}
    ctrl_hotkey_map: dict[int, Element] = {}
    for code, eid in ctrl_mapping.items():
        if eid in el_by_id:
            ctrl_hotkey_map[code] = el_by_id[eid]

    def redraw() -> None:
        win.erase()
        fill_row(win, 0, cpair("title"))
        safe_addstr(win, 0, 2, "Bar (nano-style) Test Bench",
                    cpair("title") | curses.A_BOLD)
        safe_addstr(win, 2, 2, f"Action: {state.action or '(none)':30s}",
                    cpair("status"))
        safe_addstr(win, 3, 2, f"Last event: {state.last_event:40s}",
                    cpair("status"))
        safe_addstr(win, max_y - 3, 2, "[q] quit", cpair("default"))
        draw_bar(win, bar, state)
        win.refresh()

    _run_event_loop(win, bar_elements, state, logger, redraw,
                    ctrl_hotkey_map=ctrl_hotkey_map, timeout=timeout)


# --- bar-tabs -------------------------------------------------------------

def scenario_bar_tabs(win: curses.window, logger: EventLogger,
                      timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    bar = BarDef(
        style="tabs",
        items=[
            BarItem("tab_0", "0:shell",  "", "0", "switch_tab_0"),
            BarItem("tab_1", "1:edit",   "", "1", "switch_tab_1"),
            BarItem("tab_2", "2:logs",   "", "2", "switch_tab_2"),
            BarItem("tab_3", "3:build",  "", "3", "switch_tab_3"),
        ],
        row_start=max_y - 1,
        hotkey_color_pair=COLOR_PAIRS["tab_normal"],
        label_color_pair=COLOR_PAIRS["tab_normal"],
        selected_color_pair=COLOR_PAIRS["tab_selected"],
    )
    state = ScenarioState()

    def rebuild_elements() -> list[Element]:
        return build_bar_elements(bar, max_x)

    bar_elements = rebuild_elements()

    # Number keys switch tabs
    hotkey_map: dict[str, Element] = {}
    for i, el in enumerate(bar_elements):
        hotkey_map[str(i)] = el

    def on_action(action: str) -> None:
        if action.startswith("switch_tab_"):
            idx = int(action.split("_")[-1])
            state.tab_selected = idx

    def redraw() -> None:
        win.erase()
        fill_row(win, 0, cpair("title"))
        safe_addstr(win, 0, 2, "Bar (tabs) Test Bench",
                    cpair("title") | curses.A_BOLD)
        safe_addstr(win, 2, 2,
                    f"Active tab: {state.tab_selected}",
                    cpair("status"))
        safe_addstr(win, 3, 2, f"Action: {state.action or '(none)':30s}",
                    cpair("status"))
        safe_addstr(win, max_y - 2, 2, "[q] quit", cpair("default"))
        draw_bar(win, bar, state)
        win.refresh()

    _run_event_loop(win, bar_elements, state, logger, redraw,
                    hotkey_map=hotkey_map, on_action=on_action,
                    timeout=timeout)


# --- scroll-list ----------------------------------------------------------

def scenario_scroll_list(win: curses.window, logger: EventLogger,
                         timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    total_lines = 100
    visible_rows = max_y - 4  # header(2) + footer(2)
    state = ScenarioState()

    def redraw() -> None:
        win.erase()
        fill_row(win, 0, cpair("title"))
        safe_addstr(win, 0, 2,
                    f"Scroll position: {state.scroll_pos}",
                    cpair("title") | curses.A_BOLD)
        draw_hline(win, 1, 0, max_x, cpair("default"))
        end = min(state.scroll_pos + visible_rows, total_lines)
        for i, line_num in enumerate(range(state.scroll_pos, end)):
            safe_addstr(win, 2 + i, 2, f"line {line_num + 1:03d}",
                        cpair("default"))
        draw_hline(win, max_y - 2, 0, max_x, cpair("default"))
        rng = f"{state.scroll_pos}-{end - 1}"
        safe_addstr(win, max_y - 1, 2,
                    f"Total: {total_lines}  Visible: {rng}  [q] quit",
                    cpair("status"))
        win.refresh()

    def on_mouse(ev: MouseEvent) -> None:
        if ev.button == "scroll_down" and ev.pressed:
            state.scroll_pos = min(state.scroll_pos + 1,
                                   total_lines - visible_rows)
            logger.log({"type": "scroll", "button": "scroll_down",
                         "x": ev.x, "y": ev.y,
                         "position": state.scroll_pos})
        elif ev.button == "scroll_up" and ev.pressed:
            state.scroll_pos = max(state.scroll_pos - 1, 0)
            logger.log({"type": "scroll", "button": "scroll_up",
                         "x": ev.x, "y": ev.y,
                         "position": state.scroll_pos})

    _run_event_loop(win, [], state, logger, redraw,
                    on_mouse=on_mouse, timeout=timeout)


# --- anno-signals ---------------------------------------------------------

def scenario_anno_signals(win: curses.window, logger: EventLogger,
                          timeout: float | None) -> None:
    """Render known annotation patterns for end-to-end capture verification.

    This scenario is non-interactive (no mouse/click needed).  It simply
    displays various colored patterns and waits for 'q' to quit.
    """
    max_y, max_x = win.getmaxyx()
    state = ScenarioState()

    def redraw() -> None:
        win.erase()
        # Row 0: title in reverse video
        fill_row(win, 0, cpair("title"))
        safe_addstr(win, 0, 2, "Annotation Signals Test",
                    cpair("title") | curses.A_BOLD)

        # Row 2: reverse-video selected item (Signal A/B)
        safe_addstr(win, 2, 2, "  SELECTED ITEM  ",
                    cpair("title"))  # reverse = black on white

        # Row 4: colored bg highlight on plain background (Signal A)
        safe_addstr(win, 4, 2, "  ACTIVE TAB  ", cpair("item_green"))

        # Rows 6-16: structural blue bg panel (should be filtered)
        for r in range(6, 17):
            fill_row(win, r, cpair("structural_blue"))
            safe_addstr(win, r, 2, f"  panel content {r:2d}",
                        cpair("structural_blue"))

        # Row 10: highlight ON structural bg (Signal B — column disruption)
        fill_row(win, 10, cpair("highlight_on_blue"))
        safe_addstr(win, 10, 2, "> highlighted item",
                    cpair("highlight_on_blue"))

        # Row 18: dialog button as flanked run (Signal C)
        # Reverse-video padding + default-bg button + reverse-video padding
        safe_addstr(win, 18, 2, " " * 20, cpair("title"))
        safe_addstr(win, 18, 22, "[ OK ]", cpair("default"))
        safe_addstr(win, 18, 28, " " * 20, cpair("title"))

        # Row 20: mc-style bar row (Signal C — alternating runs)
        col = 0
        labels = ["Help", "Menu", "View", "Edit", "Copy", "Quit"]
        for i, label in enumerate(labels):
            hotkey = str(i + 1)
            safe_addstr(win, 20, col, f" {hotkey}", cpair("bar_hotkey"))
            col += len(hotkey) + 1
            safe_addstr(win, 20, col, f"{label:6s}", cpair("bar_label"))
            col += 6

        # Row 22: two different colors on same row (multi-label)
        safe_addstr(win, 22, 2, "  GREEN  ", cpair("item_green"))
        safe_addstr(win, 22, 14, "  RED  ", cpair("item_red"))

        # Footer
        if max_y > 23:
            safe_addstr(win, max_y - 1, 2, "[q] quit", cpair("default"))

        win.refresh()

    _run_event_loop(win, [], state, logger, redraw, timeout=timeout)


# --- unicode-items --------------------------------------------------------

def scenario_unicode_items(win: curses.window, logger: EventLogger,
                           timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    # CJK characters are 2 cells wide each
    # We need to account for display width vs character count
    elements = [
        Element("item_cjk", row=2, col_start=2, col_end=14,
                text="\u4f60\u597d\u4e16\u754c",  # 你好世界 — 4 chars, 8 cells
                color_pair=COLOR_PAIRS["item_green"],
                action="select_cjk"),
        Element("item_cafe", row=3, col_start=2, col_end=14,
                text="caf\u00e9 latt\u00e9",
                color_pair=COLOR_PAIRS["item_cyan"],
                action="select_cafe"),
        Element("item_greek", row=4, col_start=2, col_end=14,
                text="\u03b1\u03b2\u03b3\u03b4\u03b5\u03b6",  # αβγδεζ
                color_pair=COLOR_PAIRS["item_red"],
                action="select_greek"),
        Element("item_mixed", row=5, col_start=2, col_end=18,
                text="A\u4e2d B\u6587 C",  # mixed ASCII + CJK
                color_pair=COLOR_PAIRS["item_yellow"],
                action="select_mixed"),
        Element("item_blocks", row=6, col_start=2, col_end=14,
                text="\u2588\u2588\u2588\u2588\u2588\u2588",  # ██████ block chars
                color_pair=COLOR_PAIRS["item_green"],
                action="select_blocks"),
    ]
    state = ScenarioState()

    def redraw() -> None:
        win.erase()
        fill_row(win, 0, cpair("title"))
        safe_addstr(win, 0, 2, "Unicode Items Test Bench",
                    cpair("title") | curses.A_BOLD)
        for el in elements:
            safe_addstr(win, el.row, el.col_start, el.text,
                        curses.color_pair(el.color_pair))
        safe_addstr(win, 8, 2,
                    f"Selected: {state.selected or '(none)':30s}",
                    cpair("status"))
        safe_addstr(win, 9, 2, f"Last event: {state.last_event:40s}",
                    cpair("status"))
        safe_addstr(win, max_y - 1, 2, "[q] quit", cpair("default"))
        win.refresh()

    _run_event_loop(win, elements, state, logger, redraw, timeout=timeout)


# --- edge-corners ---------------------------------------------------------

def scenario_edge_corners(win: curses.window, logger: EventLogger,
                          timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    elements = [
        Element("corner_tl", row=0, col_start=0, col_end=4,
                text="[TL]", color_pair=COLOR_PAIRS["item_green"],
                action="select_tl"),
        Element("corner_tr", row=0, col_start=max_x - 4, col_end=max_x,
                text="[TR]", color_pair=COLOR_PAIRS["item_cyan"],
                action="select_tr"),
        Element("corner_bl", row=max_y - 1, col_start=0, col_end=4,
                text="[BL]", color_pair=COLOR_PAIRS["item_red"],
                action="select_bl"),
        Element("corner_br", row=max_y - 1, col_start=max_x - 4,
                col_end=max_x, text="[BR]",
                color_pair=COLOR_PAIRS["item_yellow"],
                action="select_br"),
    ]
    state = ScenarioState()
    mid_row = max_y // 2

    def redraw() -> None:
        win.erase()
        for el in elements:
            safe_addstr(win, el.row, el.col_start, el.text,
                        curses.color_pair(el.color_pair))
        safe_addstr(win, mid_row, 2,
                    f"Selected: {state.selected or '(none)':20s}",
                    cpair("status"))
        safe_addstr(win, mid_row + 1, 2,
                    f"Last event: {state.last_event:40s}",
                    cpair("status"))
        safe_addstr(win, mid_row + 2, 2, "[q] quit", cpair("default"))
        win.refresh()

    _run_event_loop(win, elements, state, logger, redraw, timeout=timeout)


# --- keylog ---------------------------------------------------------------

def scenario_keylog(win: curses.window, logger: EventLogger,
                    timeout: float | None) -> None:
    max_y, max_x = win.getmaxyx()
    state = ScenarioState()
    key_history: list[str] = []
    max_history = max_y - 6

    def redraw() -> None:
        win.erase()
        fill_row(win, 0, cpair("title"))
        safe_addstr(win, 0, 2, "Keylog Test Bench", cpair("title") | curses.A_BOLD)
        safe_addstr(win, 1, 2,
                    f"Terminal: {max_x}x{max_y}",
                    cpair("status"))
        safe_addstr(win, 2, 2,
                    f"Keys received: {len(key_history)}",
                    cpair("status"))
        # Show key history
        start = max(0, len(key_history) - max_history)
        for i, k in enumerate(key_history[start:]):
            safe_addstr(win, 4 + i, 4, k, cpair("default"))
        safe_addstr(win, max_y - 1, 2, "[q] quit", cpair("default"))
        win.refresh()

    def on_key(key: int, key_name: str) -> bool:
        """Return True to indicate the key was handled."""
        key_history.append(key_name)
        logger.log({"type": "key", "code": key, "name": key_name})
        return True  # consume all keys except 'q' (handled by event loop)

    _run_event_loop(win, [], state, logger, redraw,
                    on_key=on_key, timeout=timeout)


# ---------------------------------------------------------------------------
# Main event loop
# ---------------------------------------------------------------------------

def _run_event_loop(
    win: curses.window,
    elements: list[Element],
    state: ScenarioState,
    logger: EventLogger,
    redraw: Callable[[], None],
    *,
    hotkey_map: dict[str, Element] | None = None,
    ctrl_hotkey_map: dict[int, Element] | None = None,
    on_action: Callable[[str], None] | None = None,
    on_mouse: Callable[[MouseEvent], None] | None = None,
    on_key: Callable[[int, str], bool] | None = None,
    timeout: float | None = None,
) -> None:
    """Generic event loop for all scenarios.

    Reads keyboard input via curses and parses SGR mouse sequences from
    the raw input buffer.  Dispatches to element hit-testing, hotkey maps,
    and optional callbacks.
    """
    # Enable SGR extended mouse mode
    sys.stdout.buffer.write(b"\x1b[?1000h")  # mouse tracking
    sys.stdout.buffer.write(b"\x1b[?1006h")  # SGR extended coords
    sys.stdout.buffer.flush()

    # Use a short timeout on getch so we can poll for mouse sequences
    win.timeout(50)  # 50ms

    mouse_buf = b""
    start_time = time.monotonic()
    redraw_fn = redraw
    action_fn = on_action
    mouse_fn = on_mouse
    key_fn = on_key

    try:
        redraw_fn()
        while state.running:
            # Check timeout
            if timeout is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    state.running = False
                    break

            ch = win.getch()
            if ch == -1:
                # No input — check if we have pending mouse bytes
                if mouse_buf:
                    events, mouse_buf = parse_mouse_events(mouse_buf)
                    for ev in events:
                        _handle_mouse_event(ev, elements, state, logger,
                                            action_fn, mouse_fn)
                    redraw_fn()
                continue

            # Check for quit
            if ch == ord("q"):
                # In keylog mode, 'q' quits but is also logged
                if key_fn is not None:
                    key_fn(ch, "q")
                state.running = False
                break

            # Check for ESC — might be start of mouse sequence
            if ch == 27:  # ESC
                # Read ahead to see if it's a mouse sequence
                raw = bytes([ch])
                win.timeout(10)
                while True:
                    nc = win.getch()
                    if nc == -1:
                        break
                    raw += bytes([nc])
                    # Check if we have a complete SGR mouse sequence
                    if nc in (ord("M"), ord("m")) and b"[<" in raw:
                        break
                    # Safety limit
                    if len(raw) > 20:
                        break
                win.timeout(50)

                mouse_buf += raw
                events, mouse_buf = parse_mouse_events(mouse_buf)
                if events:
                    for ev in events:
                        _handle_mouse_event(ev, elements, state, logger,
                                            action_fn, mouse_fn)
                    redraw_fn()
                else:
                    # It was a plain ESC or unrecognized sequence
                    if key_fn is not None:
                        key_name = _describe_raw_escape(raw)
                        key_fn(ch, key_name)
                        redraw_fn()
                continue

            # Ctrl hotkeys (nano-style)
            if ctrl_hotkey_map and ch in ctrl_hotkey_map:
                el = ctrl_hotkey_map[ch]
                state.action = el.action
                state.last_event = f"hotkey ctrl+{chr(ch + 64).lower()}"
                logger.log({"type": "action", "trigger": "hotkey",
                             "element": el.id, "key_code": ch})
                if action_fn is not None:
                    action_fn(el.action)
                redraw_fn()
                continue

            # String hotkeys (number keys for mc/tabs)
            if hotkey_map and 0 <= ch <= 255 and chr(ch) in hotkey_map:
                el = hotkey_map[chr(ch)]
                state.action = el.action
                state.last_event = f"hotkey {chr(ch)}"
                logger.log({"type": "action", "trigger": "hotkey",
                             "element": el.id, "key": chr(ch)})
                if action_fn is not None:
                    action_fn(el.action)
                redraw_fn()
                continue

            # Custom key handler
            if key_fn is not None:
                key_name = _describe_key(ch)
                key_fn(ch, key_name)
                redraw_fn()
                continue

            # Curses special keys
            if ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT,
                      curses.KEY_RIGHT):
                name = {
                    curses.KEY_UP: "Up", curses.KEY_DOWN: "Down",
                    curses.KEY_LEFT: "Left", curses.KEY_RIGHT: "Right",
                }[ch]
                state.last_event = f"key {name}"
                logger.log({"type": "key", "code": ch, "name": name})
                redraw_fn()

    finally:
        # Disable mouse tracking
        sys.stdout.buffer.write(b"\x1b[?1006l")
        sys.stdout.buffer.write(b"\x1b[?1000l")
        sys.stdout.buffer.flush()


def _handle_mouse_event(
    ev: MouseEvent,
    elements: list[Element],
    state: ScenarioState,
    logger: EventLogger,
    action_fn: Callable[[str], None] | None,
    mouse_fn: Callable[[MouseEvent], None] | None,
) -> None:
    """Process a parsed mouse event."""
    # Custom mouse handler takes priority
    if mouse_fn is not None:
        mouse_fn(ev)
        return

    el = hit_test(elements, ev.x, ev.y)
    element_id = el.id if el else "none"

    if ev.button in ("scroll_up", "scroll_down"):
        logger.log({"type": "scroll", "button": ev.button,
                     "x": ev.x, "y": ev.y, "element": element_id})
        state.last_event = f"scroll {ev.button} at ({ev.x},{ev.y})"
        return

    event_type = "mouse_press" if ev.pressed else "mouse_release"
    logger.log({"type": event_type, "button": ev.button,
                 "x": ev.x, "y": ev.y, "element": element_id})
    state.last_event = f"{ev.button} {event_type} at ({ev.x},{ev.y}) -> {element_id}"

    # Only act on press, not release
    if ev.pressed and el is not None:
        state.selected = el.text.strip("[] ")
        state.action = el.action
        logger.log({"type": "action", "trigger": "click",
                     "element": el.id, "action": el.action})
        if action_fn is not None:
            action_fn(el.action)


def _describe_key(ch: int) -> str:
    """Return a human-readable name for a curses key code."""
    special = {
        curses.KEY_UP: "Up", curses.KEY_DOWN: "Down",
        curses.KEY_LEFT: "Left", curses.KEY_RIGHT: "Right",
        curses.KEY_HOME: "Home", curses.KEY_END: "End",
        curses.KEY_PPAGE: "PageUp", curses.KEY_NPAGE: "PageDown",
        curses.KEY_IC: "Insert", curses.KEY_DC: "Delete",
        curses.KEY_BACKSPACE: "Backspace",
        curses.KEY_ENTER: "Enter",
        10: "Enter", 13: "Return",
        9: "Tab", 27: "Escape",
    }
    if ch in special:
        return special[ch]
    # Function keys
    for i in range(1, 13):
        if ch == curses.KEY_F0 + i:
            return f"F{i}"
    # Ctrl keys
    if 1 <= ch <= 26:
        return f"Ctrl+{chr(ch + 64)}"
    # Printable
    if 32 <= ch < 127:
        return chr(ch)
    return f"code_{ch}"


def _describe_raw_escape(raw: bytes) -> str:
    """Describe a raw escape sequence that wasn't a mouse event."""
    if len(raw) == 1:
        return "Escape"
    # Common sequences
    seq = raw[1:]  # strip leading ESC
    known = {
        b"[A": "Up", b"[B": "Down", b"[C": "Right", b"[D": "Left",
        b"[H": "Home", b"[F": "End",
        b"[2~": "Insert", b"[3~": "Delete",
        b"[5~": "PageUp", b"[6~": "PageDown",
        b"OP": "F1", b"OQ": "F2", b"OR": "F3", b"OS": "F4",
        b"[15~": "F5", b"[17~": "F6", b"[18~": "F7", b"[19~": "F8",
        b"[20~": "F9", b"[21~": "F10", b"[23~": "F11", b"[24~": "F12",
    }
    if seq in known:
        return known[seq]
    return f"Esc+{seq!r}"


# ---------------------------------------------------------------------------
# Curses wrapper and CLI
# ---------------------------------------------------------------------------

def _main_curses(stdscr: curses.window, scenario: str, log_path: str | None,
                 expected_cols: int | None, expected_rows: int | None,
                 timeout: float | None) -> None:
    """Entry point called inside curses.wrapper()."""
    global _orig_stdout  # noqa: PLW0603

    _init_colors()
    curses.curs_set(0)  # hide cursor
    curses.noecho()
    curses.raw()        # raw mode for mouse sequence passthrough
    stdscr.keypad(True)

    max_y, max_x = stdscr.getmaxyx()
    if expected_cols is not None and max_x != expected_cols:
        raise SystemExit(
            f"Terminal width mismatch: expected {expected_cols}, got {max_x}")
    if expected_rows is not None and max_y != expected_rows:
        raise SystemExit(
            f"Terminal height mismatch: expected {expected_rows}, got {max_y}")

    logger = EventLogger(log_path)

    scenario_fns: dict[str, Callable[[curses.window, EventLogger, float | None], None]] = {
        "menu-basic": scenario_menu_basic,
        "menu-dialog": scenario_menu_dialog,
        "menu-bell": scenario_menu_bell,
        "bar-mc": scenario_bar_mc,
        "bar-nano": scenario_bar_nano,
        "bar-tabs": scenario_bar_tabs,
        "scroll-list": scenario_scroll_list,
        "anno-signals": scenario_anno_signals,
        "unicode-items": scenario_unicode_items,
        "edge-corners": scenario_edge_corners,
        "keylog": scenario_keylog,
    }

    scenario_fn = scenario_fns[scenario]
    scenario_fn(stdscr, logger, timeout)
    logger.flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TUI test bench for term-cli integration tests")
    parser.add_argument(
        "--scenario", required=True, choices=sorted(SCENARIOS.keys()),
        help="Scenario to run")
    parser.add_argument(
        "--log", default=None, metavar="FILE",
        help="Write event log to FILE (default: stdout after exit)")
    parser.add_argument(
        "--cols", type=int, default=None,
        help="Expected terminal width (validation)")
    parser.add_argument(
        "--rows", type=int, default=None,
        help="Expected terminal height (validation)")
    parser.add_argument(
        "--timeout", type=float, default=None,
        help="Auto-exit after TIMEOUT seconds (safety for tests)")
    args = parser.parse_args()

    # Save original stdout before curses takes over
    global _orig_stdout  # noqa: PLW0603
    _orig_stdout = os.fdopen(os.dup(sys.stdout.fileno()), "w")

    # Handle SIGALRM for timeout (belt-and-suspenders with in-loop check)
    if args.timeout is not None:
        def _alarm_handler(signum: int, frame: object) -> None:
            raise SystemExit("Timeout")
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(int(args.timeout) + 5)  # hard kill 5s after soft timeout

    curses.wrapper(lambda stdscr: _main_curses(
        stdscr, args.scenario, args.log, args.cols, args.rows, args.timeout))


if __name__ == "__main__":
    main()
