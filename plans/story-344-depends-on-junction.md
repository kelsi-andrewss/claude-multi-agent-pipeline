# Story 344 — Normalize depends_on into junction table with FK constraints

## Goal
Replace the JSON-in-TEXT `depends_on` column on the `stories` table with a proper `story_dependencies` junction table. This enables real FK constraints, proper JOIN-based queries instead of LIKE, and eliminates JSON parsing in every story read.

## Changes

### 1. `tools_pm_helpers.py` — Add migration and update helpers

**a) Add migration to `startup_migrate()`:**
Add a versioned migration (version 2) that:
1. Creates the junction table:
   ```sql
   CREATE TABLE IF NOT EXISTS story_dependencies (
       story_id TEXT NOT NULL,
       depends_on TEXT NOT NULL,
       PRIMARY KEY (story_id, depends_on),
       FOREIGN KEY (story_id) REFERENCES stories(id),
       FOREIGN KEY (depends_on) REFERENCES stories(id)
   );
   CREATE INDEX IF NOT EXISTS idx_story_deps_depends ON story_dependencies(depends_on);
   ```
2. Migrates existing data: parse each story's `depends_on` JSON column, insert rows into `story_dependencies`
3. Does NOT drop the `depends_on` column (SQLite doesn't support DROP COLUMN in older versions; leave it as a deprecated field, stop writing to it)

**b) Update `_story_to_dict()`:**
- Instead of parsing `depends_on` from JSON string on the row, accept an optional `deps` parameter (list of story IDs from a JOIN)
- If `deps` is provided, use it; otherwise fall back to parsing the JSON column for backwards compatibility during migration
- Add a helper `_fetch_story_deps(conn, story_id) -> list[str]` that queries the junction table

**c) Add `_set_story_deps(conn, story_id, depends_on: list[str])`:**
- Deletes existing rows for that story_id from `story_dependencies`
- Inserts new rows
- Also updates the deprecated JSON column for backwards compat (optional — can skip if we're confident all reads go through the junction table)

### 2. `tools_pm_write.py` — Write to junction table

**a) `pm_create_story`:**
- After inserting the story row, call `_set_story_deps(conn, story_id, depends_on)` instead of storing JSON in the `depends_on` column
- Still store `'[]'` in the deprecated `depends_on` column (or remove it from INSERT entirely)

**b) `pm_update_story`:**
- Currently doesn't update `depends_on` at all (no update path exists)
- No change needed here unless we add a `depends_on` update parameter

**c) `pm_plan_items` and `_create_story_for_task`:**
- These always store `'[]'` for depends_on — no change needed since they create stories with no dependencies

### 3. `tools_pm_read.py` — Read from junction table

**a) `pm_get_story`:**
- Replace the reverse-dependency query:
  ```python
  # OLD: LIKE query on JSON column
  blocked_by_me = conn.execute(
      "SELECT id, title, state FROM stories WHERE depends_on LIKE ? AND archived = 0",
      (f'%"{story_id}"%',)
  ).fetchall()
  ```
  ```python
  # NEW: JOIN on junction table
  blocked_by_me = conn.execute(
      "SELECT s.id, s.title, s.state FROM stories s "
      "JOIN story_dependencies sd ON s.id = sd.story_id "
      "WHERE sd.depends_on = ? AND s.archived = 0",
      (story_id,)
  ).fetchall()
  ```
- Also fetch forward dependencies:
  ```python
  deps = conn.execute(
      "SELECT depends_on FROM story_dependencies WHERE story_id = ?",
      (story_id,)
  ).fetchall()
  sd["depends_on"] = [r["depends_on"] for r in deps]
  ```

### 4. `tools_pm_plan.py` — Write dependencies from Gemini plans

**a) `_apply_plan_to_story` (in helpers):**
- After writing tasks/agent/write_files, also write dependencies:
  ```python
  depends_on = plan_data.get("depends_on", [])
  if depends_on:
      _set_story_deps(conn, sid, depends_on)
  ```

**b) `pm_plan` story mode:**
- After processing plan data, call `_set_story_deps(conn, story_id, plan_data.get("depends_on", []))` instead of ignoring the depends_on field

### 5. `tools_pm_helpers.py` — Update `_story_to_dict`

The `depends_on` field in the dict should come from the junction table, not JSON parsing. Two approaches:
- **Option A**: Change `_story_to_dict` to NOT parse `depends_on` from JSON at all — callers fetch deps separately
- **Option B**: Keep `_story_to_dict` parsing the JSON column as a fallback, but preferred callers override with junction table data

**Choose Option A**: Remove `depends_on` from the JSON-parsing loop in `_story_to_dict`. Callers that need dependencies call `_fetch_story_deps()` explicitly. This keeps `_story_to_dict` simple and avoids dual sources of truth.

In `_story_to_dict`, change:
```python
for field in ("write_files", "depends_on"):
```
to:
```python
for field in ("write_files",):
```
And default `depends_on` to `[]` if not overridden by caller.

## Key Constraints
- Do NOT drop the `depends_on` column from the stories table (SQLite limitation; just stop writing meaningful data to it)
- FK constraints require PRAGMA foreign_keys=ON — add this to `_get_db()`
- The migration must be idempotent (CREATE TABLE IF NOT EXISTS)
- All LIKE queries on `depends_on` must be replaced with JOINs

## Validation
- `sqlite3 epics.db ".schema story_dependencies"` shows the junction table
- `pm_get_story` returns correct `depends_on` and `blocks` lists
- `pm_create_story` with `depends_on` parameter writes to junction table
- No LIKE queries on `depends_on` remain in any tool file
