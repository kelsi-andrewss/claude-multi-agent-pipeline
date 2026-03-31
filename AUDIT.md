# Audit Report — dotclaude orchestration harness

**Date**: 2026-03-30
**Scope**: Full project (`/Users/kelsiandrews/.claude`)
**Engine**: claude-only (Gemini rate-limited — 429 MODEL_CAPACITY_EXHAUSTED)
**Sections**: Security, Bugs, Quality (Completeness skipped — no requirements doc)

## Executive Summary

Full-project audit of the Claude Code orchestration harness covering hooks (shell + Python), MCP servers, decision_memory package, and supporting scripts. 22 findings identified: 0 critical, 3 high, 12 medium, 7 low. The dominant themes are inconsistent SQL construction patterns (f-string interpolation mixed with parameterized queries), SQLite connection management gaps (missing try/finally, TOCTOU races from multiple connections), and code duplication in correction pipeline DDL and theme-cleaning logic. Several findings overlap with existing worktree stories from a prior audit (story-1063 through story-1075). Score: 0/100 (weighted formula penalizes security findings at 4x).

## Score Breakdown

| Section | Finding Count | Weight | Weighted Deduction | Raw Deduction |
|---|---|---|---|---|
| Security | 8 | 4x | 68 | 17 |
| Bugs | 9 | 3x | 51 | 16 |
| Quality | 5 | 1x | 6 | 6 |
| **Total** | **22** | | **125** | **39** |

**Score: 0/100** (floored from -25)

---

## Security

### F-001: SQL injection via f-string in session_agenda.py **HIGH**
- **File**: hooks/lib/session_agenda.py:79
- **Description**: `cutoff_iso` interpolated directly into SQL via f-string instead of parameterized query. Value is derived from `datetime.strftime()` so not exploitable today, but breaks the parameterized pattern used elsewhere in the same function.
- **Evidence**:
```python
completed_rows = query_db(
    db_path,
    f"SELECT id, title FROM stories "
    f"WHERE state IN ('done','shipped') AND archived=0 "
    f"AND completed_at >= '{cutoff_iso}' ORDER BY completed_at DESC LIMIT 5;",
)
```
- **Source**: [claude]
- > Given the session_agenda query for completed stories, When the cutoff date is applied, Then it must use a parameterized query `(?, )` with `cutoff_iso` as a bound parameter.

### F-002: SQL injection via f-string in pm_analytics.py **HIGH**
- **File**: mcp-servers/gemini/tools_pm_analytics.py:99-104
- **Description**: `group_expr` variable interpolated into SQL via f-string. Currently set from hardcoded switch (safe), but `epic_filter` and `tp_filter` variables at lines 135, 140, 145, 157, 178 use the same fragile pattern.
- **Evidence**:
```python
rows = conn.execute(
    f"""SELECT {group_expr} as period, COUNT(*) as completed
        FROM stories
        WHERE archived = 1 AND completed_at IS NOT NULL{tp_filter}
        GROUP BY {group_expr}
        ORDER BY period DESC
        LIMIT ?""",
    tp_params + [lookback]
).fetchall()
```
- **Source**: [claude]
- > Given f-string SQL in pm_analytics.py, When group expressions are built, Then filter fragments like `epic_filter` must use parameterized `?` rather than string concatenation.

### F-003: Shell JSON construction via string interpolation **MEDIUM**
- **File**: scripts/conflict-check.sh:131-139
- **Description**: Git error output passed as shell `$MERGE_OUTPUT` into Python `sys.argv`. While `json.dumps` handles escaping, the shell-to-Python boundary relies entirely on quoting `"$MERGE_OUTPUT"` for safety.
- **Evidence**:
```bash
python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': 'git merge-tree failed (exit ' + sys.argv[1] + '): ' + sys.argv[2],
    ...
}))
" "$MERGE_EXIT" "$MERGE_OUTPUT"
```
- **Source**: [claude]
- > Given git error output passed to Python JSON builders, When the output contains arbitrary characters, Then the string value must go through `json.dumps` rather than string concatenation.

### F-004: SQL f-string interpolation in pm_helpers.py _next_id **MEDIUM**
- **File**: mcp-servers/gemini/tools_pm_helpers.py:188,233,238
- **Description**: `_next_id` interpolates `table` and `prefix_len` into SQL via f-string. Table goes through `_validate_table_name()` (safe), but `prefix_len` is an integer from `len(prefix)` with no explicit validation.
- **Evidence**:
```python
actual_max = conn.execute(
    f"SELECT MAX(CAST(SUBSTR(id, {prefix_len + 1}) AS INTEGER)) FROM {table}"
).fetchone()[0] or 0
```
- **Source**: [claude]
- **Related**: Worktree `story/tools-pm-helpers-py-add-allowlist-valida-1075--code` exists
- > Given `_next_id` table name interpolation, When the function is called, Then table names must pass `_validate_table_name` and `prefix_len` should be validated as a positive integer.

### F-005: LIKE wildcard abuse in list_by_domain **MEDIUM**
- **File**: decision_memory/store.py:432
- **Description**: `list_by_domain` uses `LIKE ?` with `f"%{domain}%"` — properly parameterized, but domain input is not sanitized for SQL LIKE special characters (`%`, `_`). A domain containing `%` matches unintended rows.
- **Evidence**:
```python
rows = conn.execute(
    "... WHERE status = 'active' AND (domain = ? OR domain LIKE ?) ...",
    (domain, f"%{domain}%", limit),
).fetchall()
```
- **Source**: [claude]
- > Given a domain search query, When the domain contains LIKE wildcards, Then `%` and `_` should be escaped before the LIKE clause.

### F-010: f-string SQL in pm_read.py and pm_organize.py **MEDIUM**
- **File**: mcp-servers/gemini/tools_pm_read.py:127,206,246,273,278,289,296,325
- **Description**: Multiple queries build SQL by concatenating filter fragments (`epic_filter`, `where`) into f-strings. Filter values are parameterized but the SQL structure is assembled via string concat — fragile and inconsistent with the parameterized approach elsewhere.
- **Evidence**:
```python
f"SELECT * FROM stories WHERE {where} ORDER BY COALESCE(order_idx, 2147483647), id", params
```
- **Source**: [claude]
- > Given dynamic SQL in PM tools, When filter conditions are added, Then the pattern should consistently use `?`-parameterized fragments or document why f-string assembly is safe.

### F-015: Dynamic SQL column construction in pm_update_story/epic/task **LOW**
- **File**: mcp-servers/gemini/tools_pm_write.py:475,576,622
- **Description**: UPDATE SET clauses built by appending `"column_name = ?"` strings and joining. Column names are hardcoded literals (not user input) — quality observation, not exploitable.
- **Evidence**:
```python
conn.execute(
    f"UPDATE stories SET {', '.join(updates)} WHERE id = ?", params
)
```
- **Source**: [claude]
- > Given dynamic UPDATE construction, When reviewed, Then column names in the `updates` list must remain hardcoded string literals.

### F-016: Multi-layered f-string SQL in session_om_query.py **MEDIUM**
- **File**: hooks/lib/session_om_query.py:43-52
- **Description**: `decay_score` is a fully interpolated SQL expression with `DEFAULT_DECAY` (float constant) and `int(now)` (Unix timestamp), then embedded into another f-string query. Hard to review for safety due to nesting.
- **Evidence**:
```python
decay_score = (
    f"feedback_score * EXP(-COALESCE(decay_lambda, {DEFAULT_DECAY}) "
    f"* (({int(now)} - COALESCE(last_seen_at, created_at)) / 86400.0))"
)
```
- **Source**: [claude]
- > Given the decay scoring expression, When applied to queries, Then constants should be documented as safe for interpolation or use parameterized inputs.

---

## Bugs

### F-007: Nested if-block logic error in load-session-context.sh **HIGH**
- **File**: hooks/load-session-context.sh:117-127
- **Description**: The correction patterns `if [[ -f "$DB_FILE" ]]` check is nested inside an identical outer check, making it redundant. Indentation suggests the author intended these as sequential siblings, not nested. The correction patterns section can never execute independently.
- **Evidence**:
```bash
  if [[ -f "$DB_FILE" ]]; then
    python3 -m hooks.lib.session_agenda "$DB_FILE" "$HOME/.claude"

  # Correction patterns — from correction_groups DB table
  if [[ -f "$DB_FILE" ]]; then
    python3 -m hooks.lib.session_agenda --corrections "$DB_FILE"
  fi

  fi
fi
```
- **Source**: [claude]
- **Related**: Worktree `story/load-session-context-sh-extract-7-python-1074--code` exists
- > Given the session context loader, When it runs correction patterns, Then the block should be at the same nesting level as session_agenda (remove redundant inner if).

### F-008: Connection not closed on exception in signal_processor.py main_logic **MEDIUM**
- **File**: hooks/lib/signal_processor.py:1155-1248
- **Description**: `conn` opened at line 1156. If an exception occurs between lines 1170-1247, connection is not closed. `conn.close()` at line 1248 only runs on happy path. Early returns at lines 1194/1200 correctly close, but exceptions in correction matching or signal update loops leak the connection.
- **Evidence**:
```python
conn = sqlite3.connect(db_path, timeout=10)
# ... many operations ...
conn.commit()
conn.close()  # only reached on success
```
- **Source**: [claude]
- **Related**: Worktree `story/signal-processor-py-try-finally-for-sqli-1069--code` exists
- > Given `main_logic`, When any exception occurs after connection open, Then the connection must be closed (use try/finally or context manager).

### F-009: Connection not closed on exception in stop_processor.py **MEDIUM**
- **File**: hooks/lib/stop_processor.py:176-252
- **Description**: `stage_auto_distillation` opens connection at line 176 via `_connect_db()`. `conn.close()` at line 251 is not in a finally block. Exceptions during embedding/LLM clustering or the promotion loop will leak the connection.
- **Evidence**:
```python
conn = _connect_db(db_file)
# ... many operations that can throw ...
conn.close()  # line 251, not in finally
```
- **Source**: [claude]
- **Related**: Worktree `story/stop-processor-py-ftruncate-lock-file-1070--code` exists
- > Given `stage_auto_distillation`, When any stage raises an exception, Then the connection must still be closed (use try/finally).

### F-012: _fetch_decision missing domain and related_decisions fields **MEDIUM**
- **File**: decision_memory/search.py:197-226
- **Description**: `SearchEngine._fetch_decision` SELECTs only 8 columns, omitting `domain` and `related_decisions`. The `Decision` dataclass defaults these to `None`, so search results always show `domain=None` even when data exists. This causes `_format_decision` in the MCP server to skip domain display.
- **Evidence**:
```python
row = self._conn.execute(
    "SELECT id, content, reasoning, status, source, superseded_by, "
    "created_at, updated_at FROM decisions WHERE id = ?",
    (decision_id,),
).fetchone()
# Missing: domain and related_decisions
```
- **Source**: [claude]
- **Related**: Worktree `story/decision-memory-store-and-types-1071--code` exists
- > Given a decision search result, When the decision has domain data, Then those fields must be populated in the returned Decision object.

### F-013: _db_connection context manager does not rollback on exception **MEDIUM**
- **File**: hooks/lib/om_write.py:42-50
- **Description**: The `_db_connection()` context manager yields the connection but does not call `conn.rollback()` on exception. SQLite auto-rollbacks uncommitted transactions on close, but explicit rollback is safer.
- **Evidence**:
```python
@contextmanager
def _db_connection():
    conn = sqlite3.connect(OM_DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
    finally:
        conn.close()
```
- **Source**: [claude]
- > Given `_db_connection`, When an exception occurs, Then explicitly rollback before closing.

### F-017: enforce_budget can exceed budget on partial commit failure **MEDIUM**
- **File**: hooks/lib/om_write.py:123-162
- **Description**: `enforce_budget` deletes entries to make room but does NOT commit — caller is responsible. If the caller's INSERT succeeds but commit fails, budget enforcement deletes are lost while the new row persists. The design is correct if caller commits atomically, but the contract is fragile.
- **Evidence**:
```python
def enforce_budget(conn, primary_tag):
    """Delete oldest entries to make room. Uses caller-provided connection.
    Does NOT commit — caller is responsible for committing."""
```
- **Source**: [claude]
- > Given enforce_budget, When deletes and insert are performed, Then both must be in the same atomic transaction (document this contract explicitly).

### F-018: Dual locking mechanism (PIDFILE + flock) with TOCTOU window **LOW**
- **File**: hooks/session-learning-check.sh:61-68
- **Description**: Shell uses PIDFILE + `kill -0` to check if stop-processor is running. Python uses `fcntl.flock`. Two independent locking mechanisms. TOCTOU window between `kill -0` check and `nohup` spawn. Flock is the authoritative lock; PIDFILE is advisory.
- **Evidence**:
```bash
if [[ -f "$PIDFILE" ]]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
  if kill -0 "$OLD_PID" 2>/dev/null; then
    exit 0
  fi
fi
```
- **Source**: [claude]
- > Given the dual locking mechanism, When a stop-processor is spawned, Then document PIDFILE as advisory with flock as authoritative.

### F-019: process_scope_overlap runs in separate transaction from record() **MEDIUM**
- **File**: decision_memory/store.py:354-390
- **Description**: `record()` commits at line 148, then `process_scope_overlap()` at line 149 runs in a separate connection/transaction. If `process_scope_overlap` fails, the new decision is committed but scope overlap processing is lost. Should share the same transaction.
- **Evidence**:
```python
def process_scope_overlap(self, decision_id, new_patterns):
    existing = self.list_all(status="active")  # opens/closes conn 1
    conn = self._get_connection()  # opens conn 2
```
- **Source**: [claude]
- > Given `record` + `process_scope_overlap`, When a decision with scope overlap is recorded, Then overlap processing should share the same transaction.

### F-020: list_by_domain query omits domain field from SELECT **LOW**
- **File**: decision_memory/store.py:427-460
- **Description**: The SELECT omits the `domain` column. `related_decisions` ends up at the wrong positional index, and the returned Decision object has no domain info despite the query filtering by domain.
- **Evidence**:
```python
"SELECT id, content, reasoning, status, source, superseded_by, "
"created_at, updated_at, related_decisions FROM decisions "
"WHERE status = 'active' AND (domain = ? OR domain LIKE ?) ..."
```
- **Source**: [claude]
- > Given `list_by_domain`, When decisions are returned, Then `domain` field must be in the SELECT and populated on the Decision object.

---

## Quality

### F-006: Dead variable prev_assistant_had_tool_use **LOW**
- **File**: hooks/lib/signal_processor.py:138
- **Description**: `prev_assistant_had_tool_use` is assigned but never read anywhere in the function or file. Remnant of a removed feature.
- **Evidence**:
```python
if turn["role"] != "user":
    prev_assistant_had_tool_use = turn.get("has_tool_use", False)
    continue
```
- **Source**: [claude]
- > Given `extract_corrections`, When dead variables exist, Then remove `prev_assistant_had_tool_use`.

### F-011: TOCTOU race from multiple connections in om_write **MEDIUM**
- **File**: hooks/lib/om_write.py:84-100,206-214,229-244
- **Description**: `om_write` calls `dedup_check` (opens conn 1), then opens conn 2 for update or conn 3 for insert. Two concurrent calls could both pass dedup_check, then both insert — creating duplicates.
- **Evidence**:
```python
existing_id, embedding = dedup_check(content, primary_tag)  # conn 1
if existing_id is not None:
    with _db_connection() as conn:  # conn 2
        cursor.execute("UPDATE memories SET ...")
else:
    with _db_connection() as conn:  # conn 3
        cursor.execute("INSERT INTO memories ...")
```
- **Source**: [claude]
- **Related**: Worktree `story/om-write-py-pass-embedding-from-dedup-1073--code` exists
- > Given concurrent `om_write` calls, When both pass dedup_check, Then only one should insert (use single connection for check-then-insert).

### F-014: Duplicated correction_groups DDL in 3 files **LOW**
- **File**: hooks/lib/signal_processor.py:362-378, scripts/log-correction.sh:50-66, hooks/lib/stop_processor.py:289-301
- **Description**: `correction_groups` table schema defined in three separate places. Schema changes must be synchronized across all three. The stop_processor version is slightly different (migration variant).
- **Source**: [claude]
- > Given correction_groups schema, When it needs to change, Then there should be a single source of truth DDL imported by all consumers.

### F-021: Raw connection without WAL/busy_timeout in MCP server **LOW**
- **File**: mcp-servers/decisions/server.py:274-290
- **Description**: `get_decision` MCP tool opens `sqlite3.connect(run_db, timeout=5)` without setting WAL mode or `busy_timeout`, unlike every other connection in the project. Inconsistent with `_connect_db()` helper pattern.
- **Evidence**:
```python
rconn = sqlite3.connect(run_db, timeout=5)
```
- **Source**: [claude]
- > Given DB connections in MCP tools, When connecting to run-state.db, Then use a consistent connection helper with WAL mode and busy_timeout.

### F-022: Duplicated theme-cleaning regex across clustering functions **LOW**
- **File**: hooks/lib/signal_processor.py:476-479,644-645
- **Description**: "Best theme" selection logic (strip expletive prefixes, compare lengths) is duplicated verbatim between `cluster_and_merge_corrections` and `llm_cluster_corrections`.
- **Evidence**:
```python
cleaned = re.sub(r'^(bro|omg|omfg|wtf|bruh|dude|yo)\b[,!?\s]*', '', m['theme'], flags=re.IGNORECASE).strip()
```
- **Source**: [claude]
- > Given theme-cleaning logic, When selecting best theme, Then extract a shared `_pick_best_theme(members)` helper.

---

## Prior Audit Story Overlap

The following worktree stories from a prior audit (2026-03-21) overlap with findings in this report:

| Finding | Prior Story Worktree | Status |
|---|---|---|
| F-004 | `story/tools-pm-helpers-py-add-allowlist-valida-1075--code` | worktree exists |
| F-007 | `story/load-session-context-sh-extract-7-python-1074--code` | worktree exists |
| F-008 | `story/signal-processor-py-try-finally-for-sqli-1069--code` | worktree exists |
| F-009 | `story/stop-processor-py-ftruncate-lock-file-1070--code` | worktree exists |
| F-011 | `story/om-write-py-pass-embedding-from-dedup-1073--code` | worktree exists |
| F-012 | `story/decision-memory-store-and-types-1071--code` | worktree exists |
