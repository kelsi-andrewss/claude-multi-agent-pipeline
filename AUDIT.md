# Code Audit Report — ~/.claude Orchestration Project

**Date:** 2026-03-14
**Scope:** Core infrastructure — `hooks/`, `hooks/lib/`, `scripts/`, `mcp-servers/gemini/`, `settings.json`, and key config files.
**Auditor:** Claude Sonnet 4.6 (automated)

---

## Executive Summary

This project is a sophisticated personal orchestration framework for Claude Code sessions, comprising ~50 shell/Python hook scripts, a Gemini MCP server with ~5,500 lines of tool code, a correction/preference learning pipeline, trust calibration, OpenMemory integration, and a worktree-based story execution system.

The codebase is well-structured with clear separation of concerns. The hook profile system, the correction-to-preference pipeline, and the PM database layer are thoughtfully designed. However, the audit identified **8 High**, **5 Medium**, and **6 Low** priority issues spanning injection vulnerabilities, race conditions in concurrent SQLite access, duplicated logic, silent data loss paths, and dead configuration references.

Overall, the system works and the engineering judgment is sound. The highest-risk surface is concurrent SQLite access from background processors and shell-interpolated Python heredocs throughout the hooks layer.

---

## Code Quality and Smells

### CQ-1: Duplicated embedding utilities between hooks/lib and MCP server (Medium)

**Files:** `mcp-servers/gemini/tools_knowledge.py` lines 32–46 and `hooks/lib/embedding_utils.py` lines 10–34

`tools_knowledge.py` re-implements `_get_embedding()` and `_embedding_to_blob()` rather than importing from `hooks/lib/embedding_utils.py`. The two implementations differ in timeout (30s vs 10s) and `tools_knowledge.py` does not normalize content the same way `om_write.py` does.

**Fix:** Factor a shared package or import from `hooks/lib/embedding_utils`. The 30s timeout is likely the right default for model loading.

---

### CQ-2: Shell-subprocess SQLite queries instead of Python sqlite3 module (Medium)

**Files:** `hooks/load-session-context.sh` lines 66–99 (render prefs), lines 152–156 (OM query), lines 210–312 (agenda)

Multiple Python blocks inside `load-session-context.sh` call the `sqlite3` CLI via `subprocess.run()` instead of using `import sqlite3` directly. This adds process overhead on every session start and introduces a dependency on the `sqlite3` binary being in PATH.

**Fix:** Replace `subprocess.run(["sqlite3", ...])` with `sqlite3.connect()` + cursor queries. The Python `sqlite3` stdlib is already used in the same script (lines 36–53).

---

### CQ-3: Inline Python repeated across five hooks (Low)

**Files:** `hooks/load-session-context.sh`, `hooks/guard-direct-edit.sh`, `hooks/inject-tier2-context.sh`, `hooks/cost-alert.sh`, `hooks/guard-protected-files.sh`

The pattern of extracting `tool_input.file_path` from JSON stdin appears verbatim in 5+ hooks. There is no shared helper.

**Fix:** Extract `hooks/lib/parse_hook_input.py` callable as `FILE_PATH=$(echo "$INPUT" | python3 hooks/lib/parse_hook_input.py file_path)`.

---

### CQ-4: Three near-identical `_ensure_*_column` functions (Low)

**File:** `mcp-servers/gemini/tools_pm_helpers.py` lines 329–379

`_ensure_order_idx_column`, `_ensure_read_files_column`, `_ensure_test_files_column` follow the same try/ALTER TABLE/catch-duplicate pattern.

**Fix:** Consolidate into `_ensure_column(conn, table, name, col_type, default=None)`.

---

### CQ-5: `_ensure_knowledge_tables` creates patterns table with stale CHECK constraint (Medium)

**File:** `mcp-servers/gemini/tools_pm_helpers.py` lines 382–431

`CREATE TABLE IF NOT EXISTS patterns` in `_ensure_knowledge_tables` contains `CHECK (category IN ('react', 'firebase', ...))`. Migration v5 drops this constraint by replacing the table. If the table was first created by `_ensure_knowledge_tables` before migration v5 ran, it gets the restrictive CHECK. Then if migration v5 was already stamped as applied, the constraint is never removed.

**Fix:** Remove the `CHECK (category IN (...))` from `_ensure_knowledge_tables` to match the v5 target schema.

---

### CQ-6: Signal processing logic duplicated between stop_processor and signal_processor (Medium)

**Files:** `hooks/lib/stop_processor.py` lines 89–187 vs `hooks/lib/signal_processor.py` lines 672–778

`stage_signal_processing()` reproduces the full logic of `signal_processor.main()`. Bug fixes must be applied in both places.

**Fix:** Extract `signal_processor.main_logic(transcript_path, db_file, session_id)` from `main()`. Make `stage_signal_processing()` call it instead.

---

### CQ-7: `globals().update()` for MCP tool registration obscures tools from static analysis (Low)

**File:** `mcp-servers/gemini/server.py`

```python
globals().update(_r_gemini(mcp) or {})
```

This makes all registered tools invisible to `grep`, type checkers, and IDE navigation. FastMCP registers tools at decoration time, so the `globals()` update is unnecessary.

**Fix:** Remove `globals().update(...)` and let FastMCP's decoration handle registration.

---

### CQ-8: Inconsistent tilde vs absolute paths in settings.json (Low)

**File:** `settings.json`

Some hooks use `~/.claude/hooks/...`, others use `/Users/kelsiandrews/.claude/tracking/...`. Both work but inconsistency makes grepping for hook references harder and the absolute paths are non-portable.

**Fix:** Standardize on tilde-based paths. The `hook_generator.py` already normalizes to tilde (line 239).

---

### CQ-9: Dead compliance hooks in settings.json cause per-invocation timeout (Low)

**Files:** `settings.json` lines 81–89, `hooks/compliance/` (contains only `.gitkeep`)

`settings.json` references two compliance hook scripts that don't exist on disk. The `_was_previously_generated` check in `hook_generator.py` prevents re-generation but the stale settings entries cause a timeout penalty on every Skill tool invocation.

**Fix:** Remove the dead hook entries from `settings.json`. Add a startup reconciliation step to `load-session-context.sh` that prunes non-existent hook paths from settings.

---

### CQ-10: `_compute_simhash` in om_write.py uses MD5 truncation, not SimHash (Low)

**File:** `hooks/lib/om_write.py`

The function is named `_compute_simhash` but uses MD5 hex truncation. MD5 is an exact-match hash — it does not detect near-duplicate content. Maintainers expecting near-duplicate detection will be misled.

**Fix:** Rename to `_content_hash` or implement actual SimHash for near-duplicate detection.

---

### CQ-11: `format_response.py` at 853 lines approaching decomposition threshold (Low)

**File:** `mcp-servers/gemini/format_response.py`

Single-responsibility module but at 853 lines it's approaching the point of needing split by domain.

**Fix:** Not urgent. Flag for decomposition at ~1000 lines into `format_pm_read.py`, `format_pm_write.py`, etc.

---

## Identified Bugs and Fixes

### BUG-1: Shell variable interpolation into Python heredocs creates injection and breakage (High)

**Files:** `hooks/guard-direct-edit.sh` lines 109–146, `hooks/load-session-context.sh` multiple blocks

Python blocks in shell scripts interpolate shell variables directly:

```python
db_path = '$DB_FILE'
file_path = '$FILE_PATH'
```

If `$FILE_PATH` contains a single quote (e.g., a file named `it's_config.js`), the Python string literal breaks. The `2>/dev/null` silently swallows the SyntaxError and the edit falls through to the generic block message — not the scope-aware message.

**Fix:** Pass variables as `sys.argv` arguments instead of interpolating:

```bash
RESULT=$(python3 - "$DB_FILE" "$FILE_PATH" <<'PYEOF'
import sys
db_path = sys.argv[1]
file_path = sys.argv[2]
PYEOF
)
```

This pattern is correctly used in `hooks/load-session-context.sh` (line 36) and `scripts/log-correction.sh` (line 30).

---

### BUG-2: `inject-tier2-context.sh` produces invalid JSON for context with tabs or control characters (High)

**File:** `hooks/inject-tier2-context.sh` lines 74–79

Manual JSON escaping only handles `\`, `"`, and `\n`:

```bash
CONTEXT="${CONTEXT//\\/\\\\}"
CONTEXT="${CONTEXT//\"/\\\"}"
CONTEXT="${CONTEXT//\n'/\\n}"
```

Tabs, carriage returns, and other control characters are not escaped. When context fragments contain these (e.g., code from plan files), the injected JSON is malformed.

**Fix:** Use `python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" <<< "$CONTEXT"` to produce a properly escaped JSON string.

---

### BUG-3: TOCTOU race condition in stop_processor lockfile acquisition (High)

**File:** `hooks/lib/stop_processor.py` lines 23–49

```python
if os.path.exists(path):
    # check stale, remove
    os.remove(path)
# gap — another process can write here
with open(path, "w") as f:
    f.write(str(os.getpid()))
```

Two sessions ending simultaneously can both pass the existence check and both write their PID, with one overwriting the other. The second process runs concurrently, causing SQLite write conflicts on `epics.db`.

**Fix:** Use atomic creation with `os.O_CREAT | os.O_EXCL`:

```python
import fcntl
fd = os.open(path, os.O_CREAT | os.O_RDWR)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    os.close(fd); return False
os.write(fd, str(os.getpid()).encode())
```

---

### BUG-4: `om_write.py` opens openmemory.sqlite without WAL mode or busy_timeout (High)

**File:** `hooks/lib/om_write.py` — all `sqlite3.connect()` calls

`om_write.py` never sets `PRAGMA journal_mode=WAL` or `PRAGMA busy_timeout`. The stop_processor and session-start hooks can access this database concurrently. Without WAL mode, concurrent writes fail with `SQLITE_BUSY` after the 10s connect timeout.

Compare: `stop_processor.py` line 62 correctly sets both pragmas.

**Fix:**
```python
conn = sqlite3.connect(OM_DB_PATH, timeout=10)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

---

### BUG-5: `enforce_budget` in om_write.py deletes entries before insert — non-atomic data loss (High)

**File:** `hooks/lib/om_write.py`

`enforce_budget` deletes the oldest entries to make room, then returns. The calling function then performs the insert separately. If the process crashes between the delete and the insert, entries are permanently lost with no replacement written.

**Fix:** Restructure so the insert happens within the same transaction as the delete:

```python
with conn:
    conn.execute("DELETE FROM memories WHERE id IN (...)")
    conn.execute("INSERT INTO memories ...")
```

---

### BUG-6: `_om_shadow_decision` bypasses om_write dedup/budget, sets feedback_score=0 causing immediate pruning (High)

**File:** `mcp-servers/gemini/tools_knowledge.py` lines 49–90

`_om_shadow_decision` writes directly to the `memories` table with raw `INSERT OR IGNORE` keyed on UUID (always unique), bypassing:
- Tag whitelist validation
- 0.85 similarity dedup threshold
- Per-tag budget limits

Additionally, it sets `feedback_score=0` (line 84). Entries with `feedback_score=0` have weighted score `0 * exp(...) = 0`, which is below the prune threshold (0.01). They are pruned on the very next session start — making decision shadows effectively useless.

**Fix:** Use `om_write()` from `hooks/lib/om_write.py` with a non-zero initial `feedback_score`:

```python
from hooks.lib.om_write import om_write
om_write(content=content, tags=["decision", decision_id], user_id=user_id)
```

---

### BUG-7: `_detect_cycles` in tools_pm_helpers.py uses unbounded DFS recursion (High)

**File:** `mcp-servers/gemini/tools_pm_helpers.py`

`_detect_cycles` uses recursive DFS with no depth limit. Python's default recursion limit is 1000. On a graph with 300+ stories and a long dependency chain, this raises `RecursionError` unhandled inside an MCP tool call.

Additionally, `_set_story_deps` deletes ALL dependencies of a story when a cycle is detected, not just the cyclic one:

```python
if _detect_cycles(conn, story_id, new_deps):
    conn.execute("DELETE FROM story_deps WHERE story_id=?", (story_id,))
```

This silently wipes legitimate existing deps if a single new dep is cyclic.

**Fix for recursion:** Convert to iterative DFS:
```python
def _detect_cycles(conn, story_id, candidate_deps):
    stack = list(candidate_deps)
    visited = set()
    while stack:
        node = stack.pop()
        if node == story_id:
            return True
        if node in visited:
            continue
        visited.add(node)
        rows = conn.execute("SELECT dep_id FROM story_deps WHERE story_id=?", (node,)).fetchall()
        stack.extend(r[0] for r in rows)
    return False
```

**Fix for data loss:** Only reject the cyclic dep, keep the rest.

---

### BUG-8: `pm_triage` SQL WHERE clause contradiction when epic_id provided (High)

**File:** `mcp-servers/gemini/tools_pm_organize.py`

```python
backlog_rows = conn.execute(
    f"SELECT id, title, state, agent FROM stories s "
    f"WHERE s.epic_id = 'epic-backlog' AND s.archived = 0"
    f"{' AND s.epic_id = ?' if epic_id else ''}",
    [epic_id] if epic_id else []
).fetchall()
```

When `epic_id` is provided, this becomes `WHERE epic_id = 'epic-backlog' AND epic_id = '<user_epic>'`. A story cannot have two different `epic_id` values simultaneously — this always returns zero rows for the backlog section.

**Fix:** Skip the backlog query when `epic_id` is specified (the backlog section only makes sense for the full view):

```python
if not epic_id:
    backlog_rows = conn.execute(
        "SELECT id, title, state, agent FROM stories s "
        "WHERE s.epic_id = 'epic-backlog' AND s.archived = 0"
    ).fetchall()
else:
    backlog_rows = []
```

---

### BUG-9: `pm_create_story` hardcodes task IDs t1, t2 — collision with subsequent pm_add_task (Medium)

**File:** `mcp-servers/gemini/tools_pm_write.py`

`pm_create_story` inserts tasks with hardcoded IDs `t1`, `t2` instead of using `_add_task_to_story`. Subsequent `pm_add_task` calls compute IDs via `MAX(CAST(REPLACE(id,'t','') AS INTEGER)) + 1`, which will produce the same IDs if the story's tasks start at `t1`. This causes silent insert failures (`UNIQUE constraint`).

**Fix:** Use `_add_task_to_story` consistently for all task creation, including the initial tasks in `pm_create_story`.

---

### BUG-10: `process_session_corrections` computes project_root with one too many dirname calls (Medium)

**Files:** `hooks/lib/signal_processor.py` line 388, `hooks/lib/stop_processor.py` line 144

```python
project_root = os.path.dirname(os.path.dirname(os.path.dirname(db_file)))
```

Given `db_file = ~/.claude/.claude/epics.db`, three `dirname` calls yield `~` (HOME directory), not `~/.claude` (project root). This causes OpenMemory imports and `_check_promoted` to look in the wrong directory.

**Fix:** Use two `dirname` calls:
```python
project_root = os.path.dirname(os.path.dirname(db_file))
```

---

### BUG-11: `prune_expired` deletes entries with feedback_score=0 immediately (Medium)

**File:** `hooks/lib/om_write.py`

New entries with `feedback_score=0` have weighted score `0 * exp(-lambda * age) = 0`, which is always below the 0.01 prune threshold. They are pruned on the very first session start after creation regardless of age.

Any tool or path that inserts with `feedback_score=0` (e.g., `tools_knowledge.py` line 84) is effectively writing entries that are immediately discarded.

**Fix:** Skip pruning for entries where `feedback_score` is 0 or NULL, treating them as neutral/pending:

```python
if (score if score else 0.0) == 0.0:
    continue
```

---

### BUG-12: `cosine_similarity` silently truncates vectors of different dimension (Medium)

**File:** `hooks/lib/embedding_utils.py`

```python
def cosine_similarity(vec_a, vec_b):
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
```

`zip` truncates to the shorter vector. If Ollama model changes produce different-dimension embeddings, stored and new vectors silently produce incorrect similarity scores (biased high due to partial dot products over partial norms).

**Fix:**
```python
def cosine_similarity(vec_a, vec_b):
    if len(vec_a) != len(vec_b):
        return 0.0
    ...
```

---

### BUG-13: `guard-protected-files.sh` permission file keyed on PID-based SESSION_ID (Medium)

**File:** `hooks/guard-protected-files.sh` line 55

```bash
PERMISSION_FILE="$CLAUDE_TEMP_DIR/konva-permission-${SESSION_ID}-${PROTECTED_NAME}"
```

`$SESSION_ID` falls back to `${PPID:-$$}` when `CLAUDE_SESSION_ID` is unset. `PPID` differs for each hook invocation (each hook is a new subprocess), so the permission file written by the main session is never found by subsequent hook invocations. Protected file edits are perpetually blocked.

**Fix:** Use `CLAUDE_SESSION_ID` directly for permission file naming, or use a session-scoped fixed location: `$CLAUDE_TEMP_DIR/konva-permission-${PROTECTED_NAME}` (scoped by temp dir lifetime, which is session-bound).

---

## Recommendations for Improvements

### R-1: Startup reconciliation to prune dead hooks from settings.json (Medium)

The `hook_generator.py` reconciliation only runs during hook generation. Non-existent compliance hook entries in `settings.json` cause timeout waste on every Skill invocation. A fast pruning pass at session start would fix this without requiring manual cleanup.

---

### R-2: Single SQLite connection per om_write() call (Medium)

`om_write.py` opens and closes the connection up to 3 times per `om_write()` call (dedup check, budget enforcement, insert). Use a single connection passed through the call chain.

---

### R-3: Schema version tracking for openmemory.sqlite (Low)

Unlike `epics.db` which has a `schema_version` table and `startup_migrate()`, `openmemory.sqlite` has no migration tracking. If the schema changes, there is no migration path.

---

### R-4: Extract inline Python from shell hooks into standalone scripts (Low)

`load-session-context.sh` at 387 lines with 6 inline Python blocks is the hardest file to maintain and test. Extracting the Python into `hooks/lib/session_context.py` would enable unit testing and IDE support.

---

### R-5: MCP server startup health check for DB schema version (Medium)

`server.py` calls `startup_migrate()` at startup but there's no check when the MCP server starts after a schema-breaking change. Consider a version assertion that warns if the DB schema differs from the server's expected version.

---

### R-6: Add overall timeout to OM query block during session start (Medium)

If Ollama is running but slow (loading a model), the 5 prototype embeddings in `signal_processor.py` can each take 10 seconds — totaling 50 seconds blocking session start. The Ollama health check at line 195 uses `curl --connect-timeout 2` but doesn't cover slow responses.

**Fix:** Wrap the OM query block: `timeout 5 python3 - ...` so session start always completes promptly.

---

### R-7: `stop_processor.py` calls `process_session_corrections` twice (Medium)

Stage 1 (`stage_correction_detection`) calls `process_session_corrections()`. Stage 2 (`stage_signal_processing`) calls it again. The same corrections are counted twice per session stop, inflating correction counts and causing premature promotion to `pending_promotion`.

**Fix:** Stage 1 should own correction detection. Stage 2 should call only the signal/preference update logic, not re-run correction detection.

---

## Overall Score: 6.5/10

**Rationale:**

The orchestration architecture is well-conceived. The hook profile system for progressive strictness, the correction-to-preference pipeline with semantic dedup and budget enforcement, the structured stop-processor with staged background processing, and the worktree-based story execution model all reflect sound engineering judgment. Module boundaries are clear and the system is functional.

The score reflects:

- **-1.5: Security/correctness holes.** Shell variable interpolation into Python heredocs (BUG-1, BUG-2) creates silent breakage on paths with quotes or control characters. The non-atomic budget enforcement (BUG-5) can silently delete entries with no replacement. The decision shadow feedback_score=0 bug (BUG-6) means every `pm_add_decision` call writes an entry that is pruned within 24 hours — the semantic memory system's persistence guarantee doesn't hold.

- **-1.0: High-impact silent failures.** `pm_triage` with epic_id always returns empty backlog (BUG-8). `process_session_corrections` computes the wrong project root (BUG-10), likely causing auto-distillation to fail. Double correction-detection calls (R-7) inflate all correction counts.

- **-0.5: Concurrency.** Missing WAL mode on openmemory.sqlite (BUG-4) and TOCTOU in lockfile acquisition (BUG-3) are real risks when sessions end simultaneously.

- **-0.5: Duplication.** Signal processing logic in two files (CQ-6) and embedding utilities in two places (CQ-1) mean bugs are fixed inconsistently.

The critical items to address first are BUG-6 (decision shadows being immediately pruned), BUG-8 (pm_triage always empty with epic_id), BUG-5 (non-atomic budget enforcement), and R-7 (double correction counting).
