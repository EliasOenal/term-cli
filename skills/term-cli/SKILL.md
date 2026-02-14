---
name: term-cli
description: Controls interactive terminal sessions for running long-lived processes, servers, REPLs, debuggers, and TUI programs without blocking. Use when you need to run dev servers (npm run dev), debuggers (pdb, gdb), REPLs (python, node), databases (psql, mysql), SSH sessions, or editors (vim, nano) — any interactive or blocking program.
allowed-tools: Bash(term-cli:*)
---

# Terminal Session Control

**You can now run any interactive application using term-cli** — dev servers, debuggers, REPLs, databases, SSH sessions, editors, and TUIs — without blocking.

**Debuggers encouraged:** Prefer **interactive debuggers** (`pdb`, `gdb`) via `term-cli` whenever appropriate for the task. This complements (and is often superior to) print-based debugging: set breakpoints, step, inspect state, then `capture` to reason.

**Think concurrently:** term-cli runs long tasks in the background. Start tests/builds/servers in one session while you write docs or investigate code in parallel. Once all other tasks are done, check back with `wait`/`capture`. Tip: occasionally run `date +"%H:%M:%S"` in a session to see when things happened, estimate future execution and to calibrate your own loop speed.

**Self-documenting:** Run `term-cli --help` or `term-cli <command> --help` for complete usage details.

## Quick Start

```bash
term-cli start --session dev && term-cli run --session dev "make test"
# ... do other work ...
term-cli wait --session dev && term-cli capture --session dev
term-cli kill --session dev
```

## Commands

### Session Management

```bash
term-cli start --session NAME --cwd /path
term-cli kill --session NAME
term-cli list
term-cli status --session NAME
```

### Running Commands

```bash
term-cli run --session NAME "make test" --wait --timeout 60   # default: 10s
```

### Sending Input

```bash
term-cli send-text --session NAME ":wq" --enter && term-cli wait --session NAME
term-cli send-key --session NAME C-c
term-cli send-stdin --session NAME < file.txt
```

Keys: `C-c` `C-d` `C-z` `C-u` `C-l` (ctrl), `Enter` `Escape` `Tab` `Space` `BSpace`, `Up` `Down` `Left` `Right`, `Home` `End` `PPage` `NPage`, `F1`-`F12`

### Capturing Output

```bash
# Visible screen only (default: physical rows, trimmed, no ANSI)
# Prefer this — it's almost always enough
term-cli capture --session NAME

# Last N physical rows from the bottom of the visible screen
term-cli capture --session NAME --tail 10

# Last N logical lines from scrollback+visible history (joins wrapped lines)
# Use only when you need output that scrolled off-screen
term-cli capture --session NAME --scrollback 20

# Include ANSI escape codes (colors) — works with any mode
term-cli capture --session NAME --scrollback 10 --raw
```

### Waiting

**Prefer `wait`** — it detects shell prompts ($, %, #), REPL prompts (>>>, (Pdb), >), and is fastest.

```bash
term-cli wait --session NAME
```

**Use `wait-idle` for TUIs** (vim, htop, less) that don't have a detectable prompt — waits for screen to settle:

```bash
term-cli wait-idle --session NAME                                      # defaults: 2s idle, 10s timeout
```

**Use `wait-for` sparingly** — waits for pattern in screen output:

```bash
term-cli wait-for --session NAME "error" "success" --ignore-case --print-match
term-cli wait-for --session NAME "error" --print-match-context 3             # match + 3 lines above/below
```

⚠️ **Warning:** `wait-for` matches the entire screen including your echoed command:

```bash
# WRONG — pattern appears in echoed command, triggers immediately - WRONG
term-cli send-text --session NAME "./build.sh && echo DONE" --enter
term-cli wait-for --session NAME "DONE"
# ↑ Problem: The screen now shows "./build.sh && echo DONE" so "DONE" matches instantly

# RIGHT — wait for program output (not your own marker)
term-cli run --session NAME "npm run dev"
term-cli wait-for --session NAME "Listening on port"

# RIGHT — assemble pattern during print so it doesn't appear in command
term-cli send-text --session NAME "./build.sh && printf 'DON' && printf 'E\n'" --enter
term-cli wait-for --session NAME "DONE"

# BEST — use wait or run --wait when possible
term-cli run --session NAME "./build.sh" --wait
```

### Human Assistance

When you need human help (passwords, CAPTCHAs, manual intervention):

```bash
term-cli request --session NAME --message "Please enter SSH password"
term-cli request-wait --session NAME                                   # default timeout: 300s (5 min)
term-cli request-status --session NAME
term-cli request-cancel --session NAME
```

**How it works:** Your human runs `term-assist list` to see pending requests, then `term-assist attach --session NAME` to join. A status bar shows your message. When finished, they press **Ctrl+B Enter** to complete — they can optionally type a response message for you. `request-wait` then returns and you continue.

If they detach with Ctrl+B d while a request is still pending, `request-wait` fails with exit code 4.

### Other Commands

```bash
term-cli resize --session NAME --cols 120 --rows 40
term-cli scroll --session NAME -50
term-cli pipe-log --session NAME /tmp/out.log
term-cli unpipe --session NAME
```

## Example: Concurrency (Run long tasks while you work)

```bash
term-cli start --session tests && term-cli run --session tests 'date +"%H:%M:%S"; pytest -q'
# ... do other work in parallel ...
term-cli wait --session tests --timeout 1800; term-cli capture --session tests
term-cli kill --session tests
```

## Example: Dev Server

```bash
term-cli start --session server && term-cli run --session server "npm run dev"
term-cli wait-idle --session server --timeout 15 && term-cli capture --session server
# ... later ...
term-cli send-key --session server C-c && term-cli wait --session server
term-cli kill --session server
```

## Example: Python Debugger (pdb)

```bash
term-cli start --session debug && term-cli run --session debug "python3 -m pdb script.py" && term-cli wait --session debug
term-cli send-text -s debug "b 42" --enter && term-cli wait -s debug      # breakpoint
term-cli send-text -s debug "c" --enter && term-cli wait -s debug         # continue
term-cli send-text -s debug "p some_var" --enter && term-cli wait -s debug && term-cli capture -s debug --tail 5
term-cli send-text -s debug "q" --enter; term-cli wait -s debug           # quit (may need 'y' to confirm)
term-cli kill --session debug
```

## Example: SSH with Password (Human Helps)

```bash
term-cli start --session remote && term-cli run --session remote "ssh user@host"
term-cli wait --session remote && term-cli capture --session remote
# If password prompt shown, request human help; if shell prompt, key auth succeeded
term-cli request --session remote --message "Please enter SSH password"
term-cli request-wait --session remote && term-cli capture --session remote
```

## Tips

- **Defaults are sane.** Plain `capture` (visible screen), `wait` (10s timeout), and `start` (80x24) work for most cases. Use `--tail` to focus on just the last few rows. Only add `--timeout` or `--scrollback` when the default isn't enough.
- **Use long-form flags.** `--session`, `--timeout`, `--scrollback` over `-s`, `-t`, `-n`. Short forms save almost no tokens and hurt readability.
- **Chain commands:** Fewer tool calls = less overhead, lower token usage, faster wall clock time. Use `&&` for dependent operations (`send-text --enter && wait`), `;` to always run the next command (`wait --timeout 5; capture` — see output even on timeout).
- Remember: you can run **interactive apps** through `term-cli` (debuggers, TUIs, SSH, installers).
- **Lost context after memory compaction?** Plain `capture` first (visible screen is usually enough). Use `--scrollback 30` if the relevant output scrolled off — scrollback is your memory.
- Prefer debuggers (`pdb`/`gdb`) via `term-cli` for bug analysis; step + inspect beats print-debugging for many issues.
- Think concurrently: start long tasks in one session and keep working; check progress with `status`, `wait`, and `capture`.
- Use `--help` on any command for details: `term-cli run --help`
- Default timeout is 10s for most wait commands — increase for builds, tests, or slow operations
- `run --wait` already waits for prompt — don't add another `wait` after it
- Capture before sending keys to verify screen state
- **Unsure if a TUI is running?** `term-cli status --session NAME` shows `Screen: alternate` when a full-screen app (vim, htop, less) is active. Use `wait-idle` for alternate screen, `wait` for normal.
- Default `request-wait` timeout is 5 minutes — usually no need to override
- Locked sessions (exit code 5): agent can only `capture`, `status`, `wait-*`, `request*`, `list`, `scroll`, `pipe-log`, `unpipe`

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Runtime error |
| 2 | Invalid input |
| 3 | Timeout |
| 4 | Human detached while request pending |
| 5 | Session locked (agent read-only) |
| 127 | tmux not found |

## Feedback

As an agent, you're well-positioned to spot improvements. Found a bug or have an idea? Email the maintainer: Elias Oenal <termcli@eliasoenal.com>
