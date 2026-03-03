# Story 343 — DB connection lifecycle: startup migration, context manager everywhere

## Goal
Currently `_get_db()` runs schema migrations (`_ensure_knowledge_tables`, `_ensure_epic_columns`, pending_proposals TTL cleanup) on **every connection open**. This is wasteful and creates latency on every tool call. Move all schema bootstrapping into a one-time `startup_migrate()` called from `server.py __main__`, and replace all manual `try/finally conn.close()` patterns with the existing `_db_op()` context manager.

## Changes

### 1. `tools_pm_helpers.py` — Refactor `_get_db` and add `startup_migrate`

**a) Strip schema logic from `_get_db()`:**
- Remove `_ensure_knowledge_tables(conn)` call
- Remove `_ensure_epic_columns(conn)` call
- Remove `DELETE FROM pending_proposals WHERE created_at < datetime(...)` TTL cleanup
- `_get_db()` becomes a pure connection factory: open, set PRAGMA WAL, set busy_timeout, set row_factory, return

**b) Create `startup_migrate(db_path=None)`:**
- New module-level function
- Opens a connection via `_get_db()`
- Calls `_ensure_knowledge_tables(conn)`
- Calls `_ensure_epic_columns(conn)`
- Calls `_ensure_order_idx_column(conn)` (currently scattered across read/organize tools)
- Runs TTL cleanup: `DELETE FROM pending_proposals WHERE created_at < datetime('now', '-24 hours')`
- Commits and closes
- Add a `schema_version` table:
  ```sql
  CREATE TABLE IF NOT EXISTS schema_version (
      version INTEGER PRIMARY KEY,
      applied_at TEXT DEFAULT (datetime('now'))
  );
  ```
- Check current version, run any pending migrations in order
- For now, version 1 = the existing schema (knowledge tables, epic columns, order_idx). No new migrations needed — this just establishes the infrastructure for future ones.

**c) Add `readonly` parameter to `_db_op()`:**
- `_db_op(db_path=None, readonly=False)`
- When `readonly=True`: skip the `conn.commit()` on exit (read-only operations don't need it)
- When `readonly=False`: keep current behavior (commit on success)

### 2. `server.py` — Call `startup_migrate()` at boot

In the `if __name__ == "__main__"` block, before `mcp.run()`:
```python
from tools_pm_helpers import startup_migrate
startup_migrate()
```

This runs once at server start, not on every tool call.

### 3. Replace `_get_db()` + `try/finally conn.close()` with `_db_op()`

Every file that currently does this pattern:
```python
conn = _get_db()
try:
    # ... use conn ...
    conn.commit()
finally:
    conn.close()
```

Replace with:
```python
with _db_op() as conn:
    # ... use conn ...
    # commit happens automatically
```

For read-only operations (queries that don't modify data), use:
```python
with _db_op(readonly=True) as conn:
    # ... read-only queries ...
```

**Files to update:**

| File | Functions using `_get_db()` directly | Read-only? |
|---|---|---|
| `tools_pm_write.py` | `pm_create_story`, `pm_add_task`, `pm_plan_items`, `pm_update_story`, `pm_update_epic`, `pm_update_task` | No (all write) |
| `tools_pm_read.py` | `pm_get_epic`, `pm_get_story`, `pm_list_stories`, `pm_search`, `pm_view`, `pm_roadmap` | Yes (all read) |
| `tools_pm_organize.py` | `pm_reorder`, `pm_housekeep` | No (reorder writes; housekeep writes on confirmed=True, reads on dry-run) |
| `tools_pm_plan.py` | `pm_plan`, `pm_critique`, `pm_check_conflicts` | `pm_plan` writes; `pm_critique` reads; `pm_check_conflicts` reads |
| `tools_pm_ship.py` | `pm_ship` | No (writes) |
| `tools_pm_analytics.py` | `pm_metrics` | Yes (all read) |
| `tools_knowledge.py` | `pm_add_decision`, `pm_list_decisions`, `pm_supersede_decision`, `pm_add_pattern`, `pm_list_patterns`, `pm_deprecate_pattern` | Mixed |

**Note:** `pm_create_epic` in `tools_pm_write.py` already uses `_db_op()` — no change needed there.

**Note:** For functions that conditionally write (like `pm_housekeep` with `confirmed` parameter), always use the write version (`_db_op()` without `readonly=True`) since the context manager's commit is a no-op on read-only connections anyway. The `readonly` flag is an optimization hint, not a correctness requirement.

### 4. Remove scattered `_ensure_order_idx_column` calls

Currently called in:
- `tools_pm_read.py`: `pm_get_epic`, `pm_list_stories`, `pm_view`
- `tools_pm_organize.py`: `pm_reorder`, `pm_housekeep`

After `startup_migrate()` handles it once at boot, these calls are redundant. Remove them.

## Key Constraints
- Do NOT change the `_db_op()` API beyond adding the `readonly` parameter
- Do NOT change how connections are opened (WAL mode, busy_timeout, row_factory stay the same)
- The `_ensure_*` functions remain in helpers — they're just called from `startup_migrate()` instead of `_get_db()`

## Validation
- Server starts without errors: `python3 mcp-servers/gemini/server.py`
- `pm_list_stories`, `pm_get_story`, `pm_create_story` all work
- Schema tables exist after first boot (verify with `sqlite3 epics.db ".tables"`)
- No `_ensure_` calls remain in tool functions (only in helpers)
- No `_get_db()` calls remain in tool functions (only `_db_op()`)
