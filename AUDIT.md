# Audit Report — ~/.claude Orchestration Project

**Date:** 2026-03-21
**Engine:** Claude-only (Gemini timed out on full project scan)
**Scope:** Full project — hooks/, scripts/, skills/, mcp-servers/, decision_memory/, plugins/, tracking/

## Executive Summary

Full-project audit of the ~/.claude orchestration system covering hooks (session lifecycle), Python libraries (signal processing, memory writes, embedding, stop processing), scripts (build verification, event emission), MCP servers (Gemini, decisions), decision memory system, and plugin infrastructure. Claude-only pass (Gemini audit timed out at 120s on full project). Found 30 issues: 0 critical, 2 high, 11 medium, 17 low. The two high-severity findings are structurally significant: (1) Stage 7 pattern mining in stop_processor.py is permanently non-functional due to a schema mismatch (`what_failed` column missing from `merge_outcomes`), and (2) decision-checking hooks exist on disk but are never registered in settings.json, meaning pre/post-agent decision enforcement never fires. Score: 0/100 (weighted scoring penalizes heavily across 4 sections).

## Score Breakdown

| Section | Findings | Weight | Weighted Deduction | Raw Deduction |
|---|---|---|---|---|
| Security | 7 | 4x | 40 | 10 |
| Bugs | 7 | 3x | 39 | 13 |
| Completeness | 4 | 2x | 14 | 7 |
| Quality | 12 | 1x | 14 | 14 |
| **Total** | **30** | | **107** | **44** |

**Score: 0/100** (floored from -7)

---

## Security

### F-001 — `os.system()` with f-string interpolation
**MEDIUM** | `tracking/patch-durations.py:99` | `[claude]`

`os.system()` with f-string path interpolation. Paths containing shell metacharacters could cause unexpected behavior. Same pattern in `tracking/backfill.py:212`.

```python
os.system(f'python3 "{SCRIPT_DIR}/generate-charts.py" "{tracking_dir}" "{charts_html}" 2>/dev/null')
```

> Given a tracking directory path containing shell metacharacters, When the script runs, Then it should use `subprocess.run()` with a list of arguments instead of `os.system()`.

---

### F-002 — Dead column reference in decision check SQL
**MEDIUM** | `hooks/check-decisions-post-agent.sh:119-128` | `[claude]`

SQL query references `positive_framing` column that doesn't exist in the decisions table. The `COALESCE(d.positive_framing, d.content)` fails with `OperationalError`, caught by bare `except Exception` on line 133, causing the entire post-agent decision check to silently fail.

```sql
SELECT DISTINCT d.id, COALESCE(d.positive_framing, d.content)
```

> Given a coder agent that modifies files with decision constraints, When the post-agent hook runs, Then the SQL query should use only columns that exist in the schema (`d.content` instead of the COALESCE).

---

### F-003 — Unescaped filename in JSON payload
**LOW** | `hooks/guard-protected-files.sh:60` | `[claude]`

`PROTECTED_NAME` interpolated directly into JSON without escaping. A filename containing double-quotes would produce malformed JSON in the event log.

```bash
"{\"protected_file\":\"$PROTECTED_NAME\",\"result\":\"blocked\"}"
```

> Given a protected filename containing JSON-special characters, When the hook emits an event, Then the filename should be properly JSON-escaped.

---

### F-004 — Unescaped file path in JSON payload
**LOW** | `hooks/guard-direct-edit.sh:149,156,164` | `[claude]`

Same pattern as F-003: `$FILE_PATH` interpolated directly into JSON string literals for `emit-event.sh`.

> Given a file path containing JSON-special characters, When the guard emits an event, Then the path should be JSON-escaped.

---

### F-005 — MD5 used for content hashing
**LOW** | `hooks/lib/om_write.py:74-75` | `[claude]`

MD5 used for dedup hashing (fallback when Ollama unavailable). Not cryptographic use, but collision probability is unnecessarily high.

```python
return hashlib.md5(content.lower().strip().encode()).hexdigest()[:16]
```

> Given two different memory entries, When the fallback simhash path is used, Then the hash function should use SHA-256 (truncated) instead of MD5.

---

### F-006 — Unsanitized FTS5 query terms
**MEDIUM** | `hooks/check-decisions-pre-agent.sh:96-114` | `[claude]`

Words from agent prompts passed directly into FTS5 MATCH clause without sanitizing FTS5 operators (AND, OR, NOT, NEAR, column filters). Could alter query semantics or cause crashes.

```python
query = " OR ".join(words)
conn.execute("SELECT rowid, rank FROM decisions_fts WHERE decisions_fts MATCH ? LIMIT 5", (query,))
```

> Given an agent prompt containing FTS5 special characters, When the fallback FTS5 query runs, Then query terms should be sanitized to strip FTS5 operators.

---

### F-007 — SQL string interpolation for date value
**LOW** | `hooks/lib/session_agenda.py:79` | `[claude]`

`cutoff_iso` date value string-interpolated into SQL instead of parameterized. Currently safe (derived from `datetime.fromtimestamp()`) but violates parameterized query pattern used elsewhere.

```python
f"AND completed_at >= '{cutoff_iso}' ORDER BY completed_at DESC LIMIT 5;"
```

> Given the completed stories query, When building SQL, Then `cutoff_iso` should be a parameterized query argument (`?`).

---

## Bugs

### F-008 — `what_failed` column missing from merge_outcomes schema
**HIGH** | `hooks/lib/stop_processor.py:457-458` | `[claude]`

`stage_pattern_mining()` queries `what_failed` from `merge_outcomes`, but this column doesn't exist in the schema defined in `scripts/init-run-db.py:70-83`. Always raises `OperationalError`, caught on line 460, causing Stage 7 to silently skip. **Pattern mining has never worked.**

```python
"SELECT story_id, domain_tags, what_failed FROM merge_outcomes "
```

> Given merge_outcomes records with failure information, When stage_pattern_mining runs, Then either the `what_failed` column should be added to the schema, or the query should use existing columns (`error_classification` or `test_output` from `merge_results`).

---

### F-009 — Redundant nested DB file check
**MEDIUM** | `hooks/load-session-context.sh:117-126` | `[claude]`

Nested `if [[ -f "$DB_FILE" ]]` is inside an identical outer check, making the inner check always true. Confusing structure.

> Given epics.db exists, When the session start hook runs, Then the redundant inner check should be removed.

---

### F-010 — Dead variable `prev_assistant_had_tool_use`
**MEDIUM** | `hooks/lib/signal_processor.py:125-129` | `[claude]`

Variable assigned but never read anywhere in the function or module. Remnant of older implementation.

```python
prev_assistant_had_tool_use = turn.get("has_tool_use", False)
```

> Given the extract_corrections function, When processing turns, Then dead variable `prev_assistant_had_tool_use` should be removed.

---

### F-011 — Post-agent decision check only covers last commit
**MEDIUM** | `hooks/check-decisions-post-agent.sh:73-77` | `[claude]`

`git diff --name-only HEAD~1 HEAD` only checks the last commit. Multi-commit agents will have earlier files unchecked. The fallback (`origin/dev...HEAD`) only triggers if line 73 returns empty.

```bash
CHANGED_FILES=$(git -C "$WORKTREE_PATH" diff --name-only HEAD~1 HEAD 2>/dev/null)
```

> Given a coder agent that made 3 commits, When the post-agent decision check runs, Then it should compare against the base branch to catch all changed files.

---

### F-012 — SIGTERM handler doesn't explicitly clean up DB
**LOW** | `hooks/lib/stop_processor.py:548` | `[claude]`

SIGTERM handler calls `sys.exit(0)` which triggers atexit, but doesn't explicitly rollback any open DB transaction before releasing the lock.

```python
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
```

> Given a stop_processor with an open DB connection, When SIGTERM is received, Then the handler should ensure connections are properly closed/rolled-back.

---

### F-013 — TOCTOU race in DB replacement
**LOW** | `decision_memory/store.py:106-110` | `[claude]`

After `os.replace()` of the DB file during `sync_from_dump()`, WAL/SHM files are explicitly deleted. But another process could open the old DB between `conn.close()` and `os.replace()`. Low probability in single-user context.

> Given a concurrent process reading decisions.db, When sync_from_dump replaces the DB file, Then the replacement should be atomic and account for concurrent readers.

---

### F-014 — Correction count uses unique dates instead of total occurrences
**MEDIUM** | `hooks/lib/session_db_migrate.py:87-106` | `[claude]`

`_fix_correction_counts()` uses `len(set(dates))` which deduplicates by day. A correction occurring twice on the same day in different sessions gets counted as 1.

```python
actual = len(set(dates))
```

> Given a correction that occurred twice on the same day in different sessions, When the migration fix runs, Then the count should reflect total occurrences (`len(dates)`) not unique dates (`len(set(dates))`).

---

## Completeness

### F-015 — Decision-checking hooks never registered in settings.json
**HIGH** | `settings.json` / `hooks/check-decisions-*.sh` | `[claude]`

`check-decisions-pre-agent.sh` and `check-decisions-post-agent.sh` exist on disk with full implementations but are NOT registered in `settings.json` under any PreToolUse/PostToolUse matcher. **Decision enforcement never fires.**

> Given a coder agent launch, When PreToolUse fires for the Agent tool, Then `check-decisions-pre-agent.sh` should be registered in `settings.json` with appropriate matchers.

---

### F-016 — Stage 7 pattern mining permanently non-functional
**MEDIUM** | `hooks/lib/stop_processor.py:457` | `[claude]`

Related to F-008. ~80 lines of clustering logic that has never successfully executed due to schema mismatch. The `OperationalError` is silently caught.

> Given merge outcomes with failure data, When the stop processor runs Stage 7, Then it should successfully query and cluster failure patterns.

---

### F-017 — inject-tier2-context.sh not marked async
**LOW** | `settings.json:170-180` | `[claude]`

Script header comment says "Hook is async: true" but `settings.json` registration omits the flag. Hook blocks prompt processing synchronously.

> Given a user prompt submission, When the tier-2 context injection hook runs, Then it should be marked `"async": true` in settings.json, OR the comment should be updated.

---

### F-018 — Dead reference to tool-learnings.md
**LOW** | `tracking/stop-hook.sh:73-81` | `[claude]`

References `$HOME/.claude/tool-learnings.md` which decision-6 explicitly marks as a dead surface.

> Given decision-6 marks tool-learnings.md as dead, When the stop hook runs, Then the reference should be removed.

---

## Quality

### F-019 — process_session_corrections() does too many things
**MEDIUM** | `hooks/lib/signal_processor.py:398-518` | `[claude]`

120-line function handling 6 responsibilities: extraction, dedup, semantic matching, text matching, count/status management, and DB writes.

> Given the correction processing pipeline, When reviewing the code, Then the function should be decomposed into focused sub-functions.

---

### F-020 — Duplicate schema migration in stop_processor
**MEDIUM** | `hooks/lib/stop_processor.py:233-295` | `[claude]`

63-line inline schema migration duplicates what `session_db_migrate.py` already handles at session start.

> Given that session_db_migrate.py runs at session start, When stage_hook_generation() runs, Then it should not duplicate migration logic.

---

### F-021 — Module-level mutable state via globals
**LOW** | `hooks/lib/om_write.py:38-39` | `[claude]`

`_ollama_fallback_warned` and `_migration_done` tracked as module globals via `global` keyword.

> Given the om_write module, When used in a long-running process, Then initialization tracking should use a class or context manager pattern.

---

### F-022 — Repetitive JSON parsing across hooks
**LOW** | Multiple hook scripts | `[claude]`

Many hooks inline `python3 -c "import json,sys; ..."` for field extraction instead of using the existing `parse_hook_input.py` utility.

> Given parse_hook_input.py exists, When hooks need JSON field extraction, Then they should use the shared parser consistently.

---

### F-023 — Test code embedded in production module
**LOW** | `hooks/lib/hook_generator.py:356-507` | `[claude]`

150-line `_run_tests()` function with 16 test cases embedded in the production module instead of in `hooks/lib/tests/`.

> Given the tests directory exists, When hook_generator tests are needed, Then they should live in `hooks/lib/tests/test_hook_generator.py`.

---

### F-024 — Build exit code masked by pipe to tail
**LOW** | `scripts/build-verify.sh:137` | `[claude]`

`bash -c "$BUILD_CMD" 2>&1 | tail -30` — `$?` captures `tail`'s exit code, not the build's.

```bash
BUILD_OUTPUT=$(bash -c "$BUILD_CMD" 2>&1 | tail -30)
```

> Given a build command that fails, When output is captured, Then `PIPESTATUS[0]` or `set -o pipefail` should capture the actual build exit code.

---

### F-025 — Magic similarity threshold defined independently in two modules
**LOW** | `hooks/lib/signal_processor.py:250` + `hooks/lib/om_write.py` | `[claude]`

`SIMILARITY_THRESHOLD = 0.85` in signal_processor.py and `DEDUP_THRESHOLD = 0.85` in om_write.py — same value, no shared constant.

> Given the embedding similarity threshold, When used for dedup across modules, Then it should be imported from a shared constant.

---

### F-026 — No overall timeout on stop_processor
**MEDIUM** | `hooks/lib/stop_processor.py:526-600` | `[claude]`

7 sequential stages with no total execution time bound. Slow Ollama or locked DB could run for minutes while holding the advisory lock.

> Given a stop_processor encountering slow operations, When total execution exceeds 120 seconds, Then it should self-terminate and release its lock.

---

### F-027 — N+1 query pattern in decision search
**LOW** | `decision_memory/search.py:196-226` | `[claude]`

`_fetch_decision()` called once per result row (up to 30 calls per hybrid search). Could batch-fetch with `WHERE id IN (...)`.

> Given a hybrid search returning 15+ results, When fetching decision details, Then the implementation should batch-fetch to reduce queries from O(N) to O(1).

---

### F-028 — No None guard on correction text
**LOW** | `hooks/lib/session_render_prefs.py:40-43` | `[claude]`

`row[0].strip()` will crash with `AttributeError` if `text` column is NULL.

```python
text = row[0].strip()
```

> Given a correction_groups row with NULL text, When rendering preferences, Then the code should handle None gracefully.

---

### F-029 — Repeated capture pattern in build-verify.sh
**LOW** | `scripts/build-verify.sh:137,164,192` | `[claude]`

Identical `set +e; RESULT=$(command); EXIT=$?; set -e` pattern repeated 3 times.

> Given the repeated capture pattern, When build/lint/test commands are run, Then a shared helper function should encapsulate it.

---

### F-030 — f-string brace escaping in generated bash scripts
**MEDIUM** | `hooks/lib/hook_generator.py:129-148` | `[claude]`

Bash scripts generated as Python f-strings with `{{}}` brace escaping for embedded Python dicts. Extremely hard to read/maintain.

> Given hook template generation, When generating bash scripts, Then use `string.Template` or a dedicated templating approach instead of f-strings.

---

*Report generated 2026-03-21. Engine: Claude-only (Gemini timed out). No requirements document — completeness section uses structural analysis only.*
