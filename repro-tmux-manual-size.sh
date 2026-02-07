#!/bin/sh
# Reproducer: new-session -d -x/-y broken when window-size is manual
# and another session already exists on the same server.
#
# The bug is in default_window_size() -> clients_calculate_size() in resize.c.
# When window-size=manual and w==NULL (window not yet created), two different
# things go wrong depending on the tmux version:
#
#   tmux 3.6a:    Server crashes (NULL dereference accessing w->manual_sx)
#   tmux next-3.7 (post-6234d798): Server survives but the NULL guard causes
#                  sx/sy to be UINT_MAX, clamped to 10000x10000.
#
# Both are fixed by returning 0 (not 1) when w==NULL for manual type, so
# default_window_size() falls through to the session's default-size option.
#
# Expected: "new" session is 100x30
# Actual:   server crash (3.6a) or 10000x10000 (next-3.7)

set -e

SOCKET="repro-$$"

cleanup() { tmux -L "$SOCKET" kill-server 2>/dev/null || true; }
trap cleanup EXIT

echo "tmux version: $(tmux -V)"

tmux -L "$SOCKET" new-session -d -s existing -x 80 -y 24
tmux -L "$SOCKET" set-option -g window-size manual

# This is the step that crashes 3.6a or produces wrong sizes on next-3.7
if ! tmux -L "$SOCKET" new-session -d -s new -x 100 -y 30 2>/dev/null; then
    echo "FAIL: server crashed creating second session (tmux 3.6a NULL deref)"
    exit 1
fi

existing=$(tmux -L "$SOCKET" display-message -p -t existing '#{pane_width}x#{pane_height}')
new=$(tmux -L "$SOCKET" display-message -p -t new '#{pane_width}x#{pane_height}')

echo "existing session size: $existing  (expected 80x24)"
echo "new session size:      $new  (expected 100x30)"

if [ "$new" = "100x30" ]; then
    echo "PASS: -x/-y respected"
    exit 0
else
    echo "FAIL: -x/-y ignored (got $new, expected 100x30)"
    exit 1
fi
