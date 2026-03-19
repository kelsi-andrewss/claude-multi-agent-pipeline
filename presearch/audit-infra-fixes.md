# Audit Infrastructure Bug Fixes

## Problem Statement

**What problem?** 9 bugs and code quality issues in the hook/shell infrastructure layer, identified in AUDIT.md: shell variable injection into Python heredocs, malformed JSON from unescaped control characters, TOCTOU race in the stop processor lockfile, missing WAL/busy_timeout on OpenMemory SQLite connections, unstable PID-based SESSION_ID for permission files, subprocess sqlite3 CLI calls where Python sqlite3 module should be used, duplicated inline Python across 5 hooks, inconsistent path formatting in settings.json, and dead compliance hook entries causing 10s timeouts.

**Why fix it?** BUG-1 breaks guard-direct-edit when file paths contain single quotes (silent fall-through to wrong error message). BUG-2 produces malformed JSON that Claude Code silently ignores (no context enrichment). BUG-3 allows concurrent stop_processor instances that cause SQLite write conflicts on epics.db. BUG-4 causes SQLITE_BUSY errors when session-start pruning and stop-processor writes overlap. BUG-13 makes protected-file permission grants non-functional when CLAUDE_SESSION_ID is unset. CQ-9 wastes 10s on every /skill invocation.

**End goal:** All 9 items resolved. Hooks handle edge-case inputs (quotes, control chars) correctly. Concurrent SQLite access uses WAL+busy_timeout everywhere. Permission file lookup is stable. Skill invocations run without dead-hook timeout penalty. Inline Python extraction reduces maintenance surface.

## Overview

Fix 9 infrastructure issues across 8 write-target files (7 existing + 1 new). Grouped into 3 stories by concern: (1) shell safety fixes for heredoc injection and JSON escaping, (2) SQLite access hardening for lockfile, WAL pragmas, and subprocess-to-module migration, (3) hook infrastructure cleanup for SESSION_ID, inline Python extraction, path normalization, and dead hook removal. All changes follow established codebase patterns. No new dependencies. No schema changes.

## Summary

| Story | Items | Write Targets | Risk |
|-------|-------|---------------|------|
| Shell safety | BUG-1, BUG-2 | guard-direct-edit.sh, inject-tier2-context.sh | Low |
| SQLite hardening | BUG-3, BUG-4, CQ-2 | stop_processor.py, om_write.py, load-session-context.sh | Low-Medium |
| Hook cleanup | BUG-13, CQ-3, CQ-8, CQ-9 | guard-protected-files.sh, settings.json, parse_hook_input.py (new), guard-direct-edit.sh, guard-protected-files.sh, track-skill-changes.sh, block-env-read.sh | Low |

## Features

### Story 1: Shell safety — heredoc injection + JSON escaping (BUG-1, BUG-2)

**BUG-1: guard-direct-edit.sh (lines 109-146)**
Pass variables as sys.argv instead of interpolating into Python string literals. Change the non-quoted heredoc to a quoted heredoc (`<<'PYEOF'`). Replace `db_path = '$DB_FILE'` / `file_path = '$FILE_PATH'` with `db_path = sys.argv[1]` / `file_path = sys.argv[2]`. Also replace the `subprocess.run(['sqlite3', ...])` call inside the same Python block with `sqlite3.connect()` + `cursor.execute()` using parameterized queries.

The safe pattern already exists at load-session-context.sh line 36: `python3 - "$DB_FILE_PREFS" <<'MIGRATEEOF'` with `db_path = sys.argv[1]`.

**BUG-2: inject-tier2-context.sh (lines 122-126)**
Replace the 3 manual bash substitutions with Python JSON serialization. Current code only escapes `\`, `"`, and `\n` — misses tabs, carriage returns, and control characters 0x00-0x1F. Replace with:
```bash
ESCAPED=$(echo "$CONTEXT" | python3 -c "import json,sys; s=sys.stdin.read(); print(json.dumps(s))")
printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":%s}}' "$ESCAPED"
```
The `json.dumps()` call produces a properly quoted+escaped JSON string (including the surrounding double quotes), which slots directly into the printf template.

**Write targets:** `hooks/guard-direct-edit.sh`, `hooks/inject-tier2-context.sh`

---

### Story 2: SQLite access hardening (BUG-3, BUG-4, CQ-2)

**BUG-3: stop_processor.py lockfile (lines 23-49)**
Replace the check-then-write TOCTOU pattern with `fcntl.flock` advisory locking per decision-103. Implementation:
1. `fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)`
2. `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` — raises `BlockingIOError` if another process holds the lock
3. Write PID to the file for monitoring: `os.ftruncate(fd, 0); os.write(fd, str(os.getpid()).encode())`
4. Store `fd` so it stays open for the process lifetime (lock auto-releases on close/exit/crash)
5. `_release_lock()` becomes: `os.close(fd); os.unlink(path)`

The stale-threshold logic (lines 33-34) can be removed — advisory locks auto-release on process exit, including crash/kill.

**BUG-4: om_write.py WAL mode (6 connection sites)**
Create a module-level `_connect_om()` helper mirroring stop_processor.py's `_connect_db()`:
```python
def _connect_om():
    conn = sqlite3.connect(OM_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
```
Replace all 6 bare `sqlite3.connect(OM_DB_PATH, timeout=10)` calls (lines 47, 68, 90, 130, 168, 198) with `_connect_om()`.

**CQ-2: load-session-context.sh subprocess sqlite3 (lines 66-99, 141-146, 222-229, 321-326)**
Replace `subprocess.run(["sqlite3", "-separator", "\t", db_path, sql])` with `sqlite3.connect(db_path)` + `cursor.execute(sql)` in all 4 Python blocks. The pattern is already established at lines 36-53 of the same file. Each `query_db()` function becomes:
```python
def query_db(sql, params=()):
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []
```
Note: return format changes from `list[list[str]]` (tab-split lines) to `list[tuple]` (sqlite3 rows). All consumers must be updated to use tuple indexing instead of list indexing — but since they already use `row[0]`, `row[1]` etc., the change is transparent.

**Write targets:** `hooks/lib/stop_processor.py`, `hooks/lib/om_write.py`, `hooks/load-session-context.sh`

---

### Story 3: Hook infrastructure cleanup (BUG-13, CQ-3, CQ-8, CQ-9)

**BUG-13: guard-protected-files.sh SESSION_ID (line 55)**
Change permission file path from `$CLAUDE_TEMP_DIR/konva-permission-${SESSION_ID}-${PROTECTED_NAME}` to `$CLAUDE_TEMP_DIR/konva-permission-${PROTECTED_NAME}`. The temp dir is already session-scoped (created fresh per session by Claude Code), making the SESSION_ID component redundant. This eliminates the PPID instability entirely.

Also update the user-facing message at line 65 to reflect the new path.

**CQ-3: Extract parse_hook_input.py (new file)**
Create `hooks/lib/parse_hook_input.py`:
```python
#!/usr/bin/env python3
"""Extract fields from Claude Code hook JSON input.

Usage: echo "$INPUT" | python3 hooks/lib/parse_hook_input.py <field>
Fields: file_path, path, prompt, transcript_path, session_id, cwd, command
"""
import json, sys

def main():
    field = sys.argv[1] if len(sys.argv) > 1 else "file_path"
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if field in ("file_path", "path"):
        path = d.get("tool_input", {}).get("file_path", "")
        if not path:
            path = d.get("tool_input", {}).get("path", "")
        print(path)
    elif field == "prompt":
        print(d.get("prompt", ""))
    elif field == "command":
        print(d.get("tool_input", {}).get("command", ""))
    else:
        print(d.get(field, ""))

if __name__ == "__main__":
    main()
```
Update the 4 hooks with the duplicated pattern to use:
```bash
FILE_PATH=$(echo "$INPUT" | python3 "$HOME/.claude/hooks/lib/parse_hook_input.py" file_path)
```
Hooks to update: guard-direct-edit.sh (lines 26-33), guard-protected-files.sh (lines 27-34), track-skill-changes.sh (lines 11-18), block-env-read.sh (lines 11-17).

**CQ-8: settings.json path normalization (lines 14, 15, 140, 162)**
Replace 4 absolute paths with tilde-based equivalents:
- `/Users/kelsiandrews/.claude/tracking/stop-hook.sh` -> `~/.claude/tracking/stop-hook.sh`
- `/Users/kelsiandrews/.claude/tracking/subagent-stop-hook.sh` -> `~/.claude/tracking/subagent-stop-hook.sh`

**CQ-9: Dead compliance hooks (lines 16-17, 78-89)**
Remove from settings.json:
1. Two permission entries for non-existent compliance hook scripts (lines 16-17)
2. The entire Skill matcher block with the two dead hook commands (lines 78-89)

Verify resulting JSON is valid. The hooks/compliance/ directory and .gitkeep remain untouched.

**Write targets:** `hooks/guard-protected-files.sh`, `settings.json`, `hooks/lib/parse_hook_input.py` (new), `hooks/guard-direct-edit.sh`, `hooks/guard-protected-files.sh`, `hooks/track-skill-changes.sh`, `hooks/block-env-read.sh`

## Technical Research

### Architecture

- **Fail-safe direction**: All PreToolUse hooks fail toward blocking (exit 2). If a Python block errors out, the hook falls through to a block message. This is correct behavior — changes must preserve it.
- **Hook profile system**: profile.sh exports SESSION_ID and CLAUDE_TEMP_DIR. BUG-13 fix is scoped to guard-protected-files.sh only — do NOT change profile.sh since other hooks use SESSION_ID for different purposes (e.g., counter files in inject-tier2-context.sh line 12).
- **Async stop hook**: stop_processor.py runs detached via `nohup ... &; disown` from session-learning-check.sh. The TOCTOU race is real because two `claude` processes can exit simultaneously.
- **Connection patterns**: stop_processor.py `_connect_db()` (lines 60-64) is the canonical pattern. om_write.py is the only SQLite user that doesn't set WAL pragmas.

### Patterns

- **Safe shell-to-Python variable passing**: `python3 - "$VAR1" "$VAR2" <<'PYEOF'` with `sys.argv[1]`, `sys.argv[2]`. The single-quoted heredoc delimiter prevents shell expansion inside the Python code. Used correctly at load-session-context.sh:36 and scripts/log-correction.sh:30.
- **SQLite connection setup**: Always `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000` immediately after `connect()`. Note: `sqlite3.connect(path, timeout=10)` sets the Python-level lock timeout, NOT the SQLite busy handler. They are different mechanisms.
- **Hook error handling**: stderr for logging, exit codes for control. Silent Python failure = empty variable = fall-through behavior (usually block).

### Dependencies

No new dependencies. All fixes use Python stdlib: `fcntl` (lockfile), `sqlite3` (DB access), `json` (escaping), `os`/`sys` (general).

## Test Strategy

### Testable Assertions

**Story 1 — Shell Safety:**
1. guard-direct-edit.sh uses quoted heredoc and sys.argv (no `'$DB_FILE'` or `'$FILE_PATH'` in Python literals)
2. inject-tier2-context.sh uses `json.dumps` for escaping (no manual bash substitutions for `\\`, `\"`, `\n`)
3. A file path containing a single quote does not cause guard-direct-edit.sh Python block to error

**Story 2 — SQLite Hardening:**
4. stop_processor.py imports fcntl and uses `fcntl.flock` in `_acquire_lock` (no `os.path.exists` check)
5. om_write.py has a `_connect_om()` helper; no bare `sqlite3.connect(OM_DB_PATH` outside it
6. load-session-context.sh has zero `subprocess.run.*sqlite3` calls; has `sqlite3.connect` calls instead

**Story 3 — Hook Cleanup:**
7. guard-protected-files.sh PERMISSION_FILE path does not contain `SESSION_ID`
8. hooks/lib/parse_hook_input.py exists and is called from guard-direct-edit.sh, guard-protected-files.sh, track-skill-changes.sh, block-env-read.sh
9. settings.json contains zero `/Users/` absolute paths
10. settings.json contains zero `compliance` references

### Edge Cases

- File path with single quote: `it's_config.js` (BUG-1 trigger)
- Context string with tab characters (BUG-2 trigger)
- Two stop_processor.py instances racing for the same lockfile (BUG-3 trigger)
- Session-start prune_expired running while stop_processor om_write runs (BUG-4 trigger)
- CLAUDE_SESSION_ID unset, then attempt to grant+use protected file permission (BUG-13 trigger)

### What NOT to Test

- Hook registration in settings.json — fails obviously if malformed
- Python import mechanics — ImportError is immediate and obvious
- SQLite pragma syntax — either works or throws, no silent failure

## Blast Radius

| Target | Dependents | Failure Mode | Risk |
|--------|-----------|--------------|------|
| guard-direct-edit.sh | settings.json matcher | Python error -> edit blocked (fail-safe) | Low |
| inject-tier2-context.sh | settings.json matcher | JSON error -> no enrichment (non-fatal) | Low |
| stop_processor.py | session-learning-check.sh | Lock error -> exit cleanly | Low |
| om_write.py | stop_processor, hook_generator, load-session-context | Connect error -> returns None, logged | Low |
| load-session-context.sh | Every session start | Block error -> missing section of context | Medium |
| guard-protected-files.sh | settings.json matcher | Path error -> edits blocked (same as current bug) | Low |
| parse_hook_input.py (new) | 4 hooks after CQ-3 | Script missing -> empty var, hooks handle gracefully | Low |
| settings.json | Claude Code runtime | Malformed JSON -> all hooks stop | Medium |

## Success Criteria

1. File paths containing single quotes don't break guard-direct-edit.sh
2. Context injection handles tabs and control characters without producing malformed JSON
3. Concurrent session endings don't produce "database is locked" errors in stop_processor logs
4. No `subprocess.run.*sqlite3` calls remain in load-session-context.sh
5. Skill invocations complete without the 10s dead-hook timeout (verified via skill-telemetry.jsonl latency)
6. Protected file permission grants work regardless of CLAUDE_SESSION_ID presence
7. `settings.json` uses tilde paths consistently, with no dead hook references

## Constraints

- Hooks must complete within timeout (5s PreToolUse, 10s SessionStart)
- Do NOT modify profile.sh — other hooks depend on its SESSION_ID export
- settings.json must remain valid JSON after all edits
- fcntl.flock is the agreed lockfile approach (decision-103)
- 3 persistence surfaces: epics.db, openmemory.sqlite, run-state.db (decision-79)
- No new external dependencies

## Decisions

- **decision-103**: Use fcntl.flock for lockfile (BUG-3 fix approach)
- **decision-79**: Three persistence surfaces — all must use WAL+busy_timeout for concurrent access (BUG-4 motivation)
- **SESSION_ID fix scope**: guard-protected-files.sh only, not profile.sh (BUG-13 — avoid breaking other hooks that use SESSION_ID for counter files)
- **parse_hook_input.py**: New shared helper, callable as `python3 path/to/parse_hook_input.py <field>` — keeps hooks as bash scripts, extracts only the JSON parsing
- **JSON escaping**: Use Python json.dumps instead of building a bash escaping library — Python handles all edge cases and is already a dependency
