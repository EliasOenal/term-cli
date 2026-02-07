# AGENTS.md — Guidelines for AI Coding Agents (term-cli)

This repo is **term-cli**: a single-file Python CLI that wraps **tmux** to let agents run **interactive / long-lived / blocking** terminal programs *without attaching*. It is **TTY-first** by design.

## Read This First

**Before issuing `term-cli` commands, read `skills/term-cli/SKILL.md` end-to-end.** It’s the canonical agent playbook for correct wait strategies and common pitfalls.

- **Prefer `wait`** (prompt detection with a strong heuristic) for shells/REPLs; **use `wait-idle`** for TUIs (vim/htop/less) or screens without a detectable prompt; **use `wait-for`** only when you truly need specific text.

## Wait Semantics (Important)

- `wait` detects a **prompt** using cursor position + screen content (designed to handle SSH where old prompts remain visible).
- `run --wait` is equivalent to **send command + Enter + wait for prompt**.
- `wait-idle` is “screen stopped changing for N seconds” (best for TUIs / streaming UIs).
- `wait-for` searches the **visible screen** for **substring matches** (optionally case-insensitive). It can match echoed commands too—prefer `wait`/`run -w` when possible.

---

## CLI Cheat Sheet (Dense)

### Global

- `-L/--socket-name NAME` — use an isolated tmux server (separate socket). Useful for tests/CI.

### Sessions

```bash
# Create a sized session in a cwd, preload env, choose shell, start locked
term-cli -L t1 start -s dev -c ./proj -x 120 -y 34 -e FOO=bar -e PYTHONUNBUFFERED=1 --shell /bin/bash -l

# List (shows [LOCKED] marker)
term-cli -L t1 list

# Status (idle/running + process tree + attached + created)
term-cli -L t1 status -s dev

# Resize later (cols only here)
term-cli -L t1 resize -s dev -x 160

# Kill (refuses if humans attached unless -f; refuses if locked)
term-cli -L t1 kill -s dev -f

# Kill all (same protections; checks all unlocked first)
term-cli -L t1 kill -a -f
```

### Running + Waiting

```bash
# Run and wait for prompt to return (default wait timeout is ~10s unless -t)
term-cli run -s dev -w -t 120 "pytest -q"

# When you sent input manually (send-text -e / send-key Enter), use wait
term-cli send-text -s dev -e "python3"
term-cli wait -s dev -t 15

# TUIs / no prompt: wait until output settles
term-cli run -s dev "htop"          # no -w here
term-cli wait-idle -s dev -i 2 -t 30 # idle seconds + max timeout

# Wait for one of multiple substrings (screen match, not regex)
term-cli wait-for -s dev -t 30 -i -c "Listening on" "Ready" "Error"
```

### Input

```bash
# Literal text (no Enter unless -e)
term-cli send-text -s dev ":wq" -e

# Special keys
term-cli send-key -s dev C-c
term-cli send-key -s dev Escape
term-cli send-key -s dev Up

# Multiline (stdin -> tmux buffer -> paste)
cat <<'EOF' | term-cli send-stdin -s dev
export PATH="$HOME/bin:$PATH"
echo done
EOF
```

### Capture / Logs / Scroll

```bash
# Visible screen (trimmed by default)
term-cli capture -s dev

# Last N physical rows from visible screen
term-cli capture -s dev --tail 5

# Include scrollback (-n) and ANSI escapes (-r)
term-cli capture -s dev -n 20 -r

# Pipe output to a file; strips ANSI by default (use -r for raw)
term-cli pipe-log -s dev /tmp/dev.log
term-cli unpipe  -s dev

# Scroll viewport (negative = up). Note: uses copy-mode scroll.
term-cli scroll -s dev -50
```

---

## Abbreviations (Prefix Matching)

Any **unambiguous prefix** works.

**Known ambiguous prefixes (avoid):**
- `st`, `sta` → **start** vs **status**
- `re` → **resize** vs **request***
- `req` → **request**, **request-wait**, **request-cancel**, **request-status**

**Recommended short forms:**
- `star` = `start`, `stat` = `status`, `res` = `resize`
- `send-t` = `send-text`, `send-k` = `send-key`, `send-s` = `send-stdin`
- `wait-i` = `wait-idle`, `wait-f` = `wait-for`
- `request` (full), `request-w` / `request-c` / `request-s`

Examples:
```bash
term-cli star -s a -c . -x 100 -y 30
term-cli ru   -s a -w -t 60 "make test"
term-cli c    -s a -n 10
term-cli wait-i -s a -i 2 -t 20
term-cli request-w -s a -t 300
```

---

## Behavior Notes (What to Expect)

### Defaults & Environment

- Default terminal size: **80x24**.
- `TERM_CLI_COLS` / `TERM_CLI_ROWS` env vars override defaults.
- `start --no-size` lets tmux decide size.
- `capture` trims trailing whitespace and blank lines unless `--no-trim`.

### `status`

- Prints: session name, idle/running, foreground command (best-effort), screen mode (normal/alternate), size, locked state, attached state, created timestamp, and a process tree.
- “running” is inferred from foreground process markers (best-effort; treat as advisory).
- “Screen: alternate” means a full-screen TUI (vim, htop, less) is active — use `wait-idle` instead of `wait`.

### `pipe-log`

- Uses tmux `pipe-pane -o` so it won’t duplicate an existing pipe.
- Validates the parent directory exists.
- Default mode strips ANSI escapes; `--raw` keeps them.

### `kill`

- Refuses to kill if **locked**.
- Refuses to kill if **humans are attached**, unless `--force`.
- `kill --all` first validates **all sessions** can be killed (unlocked, and unattached unless forced).

---

## Human Collaboration (term-assist)

### Agent Side

```bash
term-cli start --session remote && term-cli run --session remote "ssh user@host"
term-cli wait --session remote && term-cli capture --session remote  # password prompt or shell (key auth)?
term-cli request --session remote --message "Please complete SSH login (password/MFA)"
term-cli request-wait --session remote && term-cli capture --session remote
```

### Human Side

```bash
term-assist list
term-assist attach --session remote
# complete the interaction
# Ctrl+B Enter => done (optional message)
# Ctrl+B d     => detach (if request still pending, agent sees exit code 4)
```

### Locked Sessions

- Create locked: `term-cli start --session NAME --locked`
- When locked, the agent can only: `capture`, `status`, `wait*`, `request*`, `list`, `scroll`, `pipe-log`, `unpipe`.
- Interactive commands (`run`, `send-*`, `resize`, `kill`) return **exit code 5**.

---

## Exit Codes (Contract)

| Code | Meaning |
|---:|---|
| 0 | Success |
| 1 | Runtime error (tmux failed, session missing, etc.) |
| 2 | Invalid input (bad args / validation) |
| 3 | Timeout (wait condition unmet) |
| 4 | Human detached while request pending |
| 5 | Session locked (agent read-only) |
| 127 | tmux not found on PATH |

Exception mapping used by the CLI:
- `FileNotFoundError` → 127
- `ValueError` → 2
- `OperationTimeout` → 3
- `HumanDetached` → 4
- `AgentLocked` → 5
- `QueryResult` → exit code carried by exception (default 1; non-error query result, printed to stdout)
- `RuntimeError` → 1

---

## Repo / Codebase Guidelines

### Non-Negotiables

- **Single-file tool** (`term-cli`): stdlib-only; no Python deps.
- The tool must remain **non-interactive**: never attach; never depend on an interactive UI.
- Input validation must be explicit and early (`--cwd` exists, `--shell` executable, `pipe-log` parent dir exists, etc.).
- Output is for humans + agents: concise, stable, trimmed.

### Design Principles

1. **Single file** — one executable Python script
2. **No deps** — stdlib + tmux only
3. **Explicit** — invalid state fails fast (`start` if exists; `kill` if missing; timeouts are errors)
4. **Human output** — plain text, stable, trimmed
5. **Self-documenting** — `term-cli --help` and `term-cli <cmd> --help`

### Code Quality & Testing

1. **Determine intended behavior first** — don't assume the app or tests are correct.
2. **Fix the source** — fix app bugs in the app; fix wrong expectations in tests.
3. **No hacks** — don't add special-cases just to satisfy assertions.
4. **No weak tests** — don't loosen checks to hide broken behavior.
5. **Fix tests when you notice issues** — even if it makes failures visible temporarily.
6. **Legitimate improvements are not hacks** — validation, clearer errors, and consistent behavior are good engineering.
7. **Use unique session names in tests** — avoid collisions; always cleanup (e.g., `finally`).
8. **Flaky tests are bugs.** Never dismiss a test as "flaky" or "pre-existing." Investigate the root cause and fix it — in the test, the app, or both.
9. **Never push to the remote repository.** The human owner pushes. Agents commit locally only.
10. **Never commit with broken tests.** Run the full test suite (`./run-tests.sh`) and `pyright` **before** committing. If tests fail, fix them first.

### Bug Reporting

**Raise potential bugs immediately.** If something looks off during development, review, manual testing, or while writing tests, don’t work around it silently—call it out.

**Keep documentation updated** If `--help`/docs and the skill disagree, review the source code (source of truth) and improve the documentation.

### Style

- Keep the structure: shebang → license → docstring → imports → constants → utilities → commands → CLI.
- Keep tmux usage readable: prefer small helpers over clever inline tmux format strings / quoting tricks.

**Typing & type checks (run these):**

- Keep `from __future__ import annotations` as the first import.
- Annotate **all** params/returns (including pytest fixtures).
- Prefer modern syntax: `list[str]`, `dict[str, int]`, `str | None`.
- Avoid `Any` and `# type: ignore` unless you can justify it.

```bash
pyright
# or, if you want to scope it:
pyright term-cli tests/
```

### Naming Conventions

- **Constants**: `SCREAMING_SNAKE_CASE` (`DEFAULT_COLS`, `EXIT_TIMEOUT`)
- **Private functions**: `_underscore_prefix` (`_eprint`, `_run_tmux`)
- **Command handlers**: `cmd_` prefix (`cmd_list`, `cmd_start`)
- **Variables/params**: `snake_case`

### Command Handler Pattern

```python
def cmd_example(args: argparse.Namespace) -> None:
    session = args.session
    _require_session(session)     # Validate existence
    _require_unlocked(session)    # Check permissions
    # ... do work ...
    print("Success message")      # Human-readable output
```

### Behavior Consistency

- Timeouts are **hard failures** (exit 3), not warnings.
- Locked sessions must be enforced uniformly (`_require_unlocked`).
- `wait-for` remains substring-based unless intentionally redesigned (and docs/tests updated).

---

## Tests & Local Smoke

If the repo provides a test runner script, use it (it’s typically faster than raw pytest):

```bash
./run-tests.sh                 # parallel + serial where needed
./run-tests.sh -s              # sequential (debugging)
```

Manual smoke (unique session name recommended in tests/CI):
```bash
S=smoke-$RANDOM
term-cli start --session "$S" && term-cli run --session "$S" --wait --timeout 10 "echo hello" && term-cli capture --session "$S" && term-cli kill --session "$S" --force
```

**Parallel tests:** never use hardcoded session names; always clean up in `finally`.

### Nested tmux testing pattern

To test behavior that requires an attached client (e.g. `term-assist attach`,
verifying `kill` refuses when humans are attached), use the **nested tmux**
pattern: run `tmux attach` or `term-assist attach` *inside* a helper term-cli
session.

tmux normally refuses to nest (it checks `$TMUX`).  Override this by prefixing
the command with `TMUX=''`:

```python
helper = unique_session_name()
term_cli("start", "-s", helper, "-x", "60", "-y", "15", check=True)
term_cli("wait", "-s", helper, "-t", "10", check=True)

# Attach to target FROM INSIDE the helper session
term_cli(
    "run", "-s", helper,
    f"TMUX='' {sys.executable} {term_assist_path}"
    f" -L {tmux_socket} attach -s {target}",
)
```

**Setup rules:**
1. The helper session needs its own dimensions (e.g. 60x15) — make them
   **different** from the target so any resize is detectable.
2. Wait for the helper's shell prompt *before* running the attach command.
3. After `run`, poll until the target session shows an attached client:
   ```python
   from conftest import retry_until
   assert retry_until(
       lambda: self._session_has_client(tmux_socket, target),
       timeout=5.0,
   )
   ```

**Cleanup rules (always in `finally`):**
1. Send the tmux detach sequence to the helper: `C-b` then `d`.
2. Wait for the helper's shell prompt to return (the inner tmux has exited).
3. Force-kill the helper session.

```python
finally:
    term_cli("send-key", "-s", helper, "C-b")
    term_cli("send-key", "-s", helper, "d")
    term_cli("wait", "-s", helper, "-t", "5")
    term_cli("kill", "-s", helper, "-f")
```

This ensures the target has zero attached clients before `session_factory`
teardown tries to kill it.  Skipping this can cause "session has attached
clients" errors during cleanup.

**Examples:** `test_session.py::TestKill::test_kill_all_atomicity`,
`test_assist.py::TestAttachPreservesSize`.
