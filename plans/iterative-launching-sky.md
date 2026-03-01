# Plan: Agile Tracking MCP Tools with SQLite Backend

## Context

The project has a mature epic/story/task tracking system in `.claude/epics.json` with shell-script-based mutations. Problems:
1. **Token waste** — epics.json grows unboundedly (184 archived stories). Every agent/skill that reads it burns tokens on dead data.
2. **No programmatic API** — AI tools can't query or mutate project state without reading raw JSON.
3. **Limited analytics** — no cycle time, throughput, or WIP tracking.

**Solution:** Replace `epics.json` with a SQLite database (`epics.db`), expose it through 13 new MCP tools on the existing Gemini server, and migrate all consumers (scripts, hooks, skills, agent docs) in a full cutover.

**Decisions:**
- Kanban flow (no sprints)
- Hybrid task model (session-scoped + persistent tasks on stories)
- Extend existing Gemini MCP server
- Full CRUD via MCP tools
- SQLite backend (zero token cost for reads — query only what you need)
- Full cutover (no dual-system maintenance)

---

## Database Schema

File: `.claude/epics.db` (SQLite, WAL mode for concurrent reads)

```sql
CREATE TABLE epics (
  id         TEXT PRIMARY KEY,  -- "epic-022"
  title      TEXT NOT NULL,
  branch     TEXT,              -- "epic/022"
  pr_number  INTEGER,
  persistent INTEGER DEFAULT 0, -- boolean
  state      TEXT DEFAULT 'active' CHECK(state IN ('active','done','shipped'))
);

CREATE TABLE stories (
  id             TEXT PRIMARY KEY,  -- "story-185"
  epic_id        TEXT NOT NULL REFERENCES epics(id),
  title          TEXT NOT NULL,
  state          TEXT DEFAULT 'draft',
  branch         TEXT,
  write_files    TEXT,              -- JSON array: '["file1.py","file2.py"]'
  needs_testing  INTEGER DEFAULT 0,
  needs_review   INTEGER DEFAULT 0,
  agent          TEXT,              -- "quick-fixer", "architect", "manual"
  model          TEXT,              -- "haiku", "sonnet", "opus"
  depends_on     TEXT,              -- JSON array: '["story-184"]'
  auto_merge     INTEGER DEFAULT 0,
  started_at     TEXT,              -- ISO 8601
  completed_at   TEXT,              -- ISO 8601
  archived       INTEGER DEFAULT 0  -- 1 = archived (replaces separate archive array)
);

CREATE TABLE tasks (
  id         TEXT NOT NULL,        -- "t1" (unique within story)
  story_id   TEXT NOT NULL REFERENCES stories(id),
  title      TEXT NOT NULL,
  state      TEXT DEFAULT 'todo' CHECK(state IN ('todo','in-progress','done','blocked','skipped')),
  blocked_by TEXT,                 -- task ID within same story
  PRIMARY KEY (story_id, id)
);

-- Indexes for common queries
CREATE INDEX idx_stories_state ON stories(state) WHERE archived = 0;
CREATE INDEX idx_stories_epic ON stories(epic_id) WHERE archived = 0;
CREATE INDEX idx_stories_branch ON stories(branch) WHERE branch IS NOT NULL;
```

**Key design:** `archived` is a boolean column on stories, not a separate table. Queries default to `WHERE archived = 0` so archived data is never returned unless explicitly requested. No token waste.

---

## Files to Modify/Create

| File | Action | Description |
|------|--------|-------------|
| `mcp-servers/gemini/server.py` | Modify | Add ~600 lines: SQLite helpers, 13 MCP tools |
| `mcp-servers/gemini/test_server.py` | Modify | Add ~400 lines of tests |
| `.claude/scripts/epics-cli.sh` | **Create** | Thin CLI wrapper for hooks/scripts to query SQLite |
| `.claude/scripts/migrate-to-sqlite.sh` | **Create** | One-time migration from epics.json → epics.db |
| `.claude/scripts/update-epics.sh` | **Delete** | Replaced by MCP tools + epics-cli.sh |
| `.claude/scripts/archive-closed-stories.sh` | **Delete** | Auto-archive handled by MCP update tool |
| `.claude/scripts/merge-latest-worktree.sh` | Modify | Replace Node.js JSON read with epics-cli.sh query |
| `hooks/guard-direct-edit.sh` | Modify | Replace Python JSON read with epics-cli.sh query |
| `hooks/load-session-context.sh` | Modify | Replace Python JSON read with epics-cli.sh query |
| `.claude/skills/health/SKILL.md` | Modify | Use `pm_` MCP tools instead of Read on JSON |
| `.claude/skills/deps/SKILL.md` | Modify | Use `pm_` MCP tools instead of Read on JSON |
| `skills/audit/SKILL.md` | Modify | Use `pm_list_stories` MCP tool for cross-ref |
| `skills/lint/SKILL.md` | Modify | Use `pm_get_story` MCP tool for branch lookup |
| `skills/flutter-audit/SKILL.md` | Modify | Use `pm_list_stories` MCP tool for cross-ref |
| `agents/todo-orchestrator.md` | Modify | Use `pm_search` MCP tool for dedup |
| `agents/epic-planner.md` | Modify | Use `pm_search` MCP tool for dedup |
| `agents/git-ops.md` | Modify | Reference epics-cli.sh instead of update-epics.sh |
| `refs/staging-schema.md` | Modify | Update to reflect SQLite schema |

---

## Step 1: Create `epics-cli.sh` — thin SQLite query helper

This replaces `update-epics.sh` for non-MCP consumers (hooks, shell scripts). It's a bash script that runs `sqlite3` commands.

```bash
#!/usr/bin/env bash
# epics-cli.sh <db-path> <command> [args...]
#
# Commands:
#   story-by-branch <branch>     → JSON: {id, epicId, title, branch, prNumber, writeFiles}
#   running-write-files           → JSON array of {state, writeFiles} for active stories
#   running-stories               → JSON array of {id, title, state, branch} for active stories
#   update-story <id> <json>      → Update story fields
#   update-epic <id> <json>       → Update epic fields
#   add-story <epic-id> <json>    → Add new story
```

This keeps hooks fast (no Python/Node.js startup — `sqlite3` is native) and provides the subset of queries that scripts need.

---

## Step 2: Create `migrate-to-sqlite.sh` — one-time migration

Reads existing `epics.json`, creates `epics.db`, populates all tables. Run once, then delete `epics.json`.

- Reads `epics[]` → inserts into `epics` table
- Reads `epics[].stories[]` → inserts into `stories` table (archived=0)
- Reads `backlog[]` → inserts into `stories` table with epic_id='backlog' (create backlog epic if needed)
- Reads `archive[]` → inserts into `stories` table (archived=1)
- Reads `story.tasks[]` → inserts into `tasks` table
- Enables WAL mode

---

## Step 3: Add SQLite helpers to server.py

Insert after redesign constants, before `DOCUMENTS`:

```python
import sqlite3
from contextlib import contextmanager

EPICS_DB = Path.home() / ".claude" / ".claude" / "epics.db"

STORY_STATES = {"draft", "ready", "in-progress", "in-review", "approved", "done", "blocked", "shipped"}
TASK_STATES = {"todo", "in-progress", "done", "blocked", "skipped"}
TERMINAL_STATES = {"done", "closed", "shipped"}
EPIC_STATES = {"active", "done", "shipped"}

VALID_STORY_TRANSITIONS = {
    "draft": {"ready", "in-progress"},
    "ready": {"in-progress", "draft"},
    "in-progress": {"in-review", "approved", "done", "blocked"},
    "in-review": {"in-progress", "approved"},
    "approved": {"done", "shipped", "in-progress"},
    "blocked": {"in-progress", "draft"},
    # "any → blocked" and "any → draft" also valid
}
```

**Helpers:**
- `_get_db() -> sqlite3.Connection` — Opens DB with WAL mode, row_factory=sqlite3.Row
- `_next_id(table, prefix) -> str` — `SELECT MAX(CAST(SUBSTR(id,len+1) AS INT)) FROM table` + 1
- `_validate_transition(current, target, valid_map, force) -> str | None`
- `_story_to_dict(row) -> dict` — Converts Row to dict, parses JSON fields (write_files, depends_on)
- `_epic_to_dict(row) -> dict` — Same for epics

No subprocess calls for mutations. Direct SQLite writes from Python (replacing the Node.js-in-bash pattern). This is safe because:
- SQLite WAL mode handles concurrent reads
- MCP tools are called sequentially by Claude (no true write concurrency)
- Atomic by default (SQLite transactions)

---

## Step 4: Add read/query MCP tools (6 tools)

| Tool | Query | Returns |
|------|-------|---------|
| `pm_list_epics(state?, include_stories?)` | `SELECT * FROM epics WHERE state=? AND ...` | Array of epic summaries (with optional inline story counts) |
| `pm_get_epic(epic_id)` | Epic + `SELECT * FROM stories WHERE epic_id=? AND archived=0` | Full epic with active stories and their tasks |
| `pm_list_stories(epic_id?, state?, agent?, include_archived?)` | Filtered query on stories table | Array of story summaries. `include_archived` defaults false. |
| `pm_get_story(story_id)` | Story + `SELECT * FROM tasks WHERE story_id=?` | Full story with tasks and reverse dependency lookup |
| `pm_board(epic_id?)` | Group by state, `WHERE archived=0` | Kanban columns with WIP counts and blocked items |
| `pm_search(query, scope?)` | `LIKE '%query%'` on title/id across epics/stories/tasks | Matched items with type and context |

---

## Step 5: Add write MCP tools (6 tools)

| Tool | Operation | Side Effects |
|------|-----------|-------------|
| `pm_create_epic(title, branch?, persistent?)` | `INSERT INTO epics` | Auto-generates next ID |
| `pm_create_story(title, epic_id?, write_files?, agent?, model?, depends_on?, needs_testing?, needs_review?)` | `INSERT INTO stories` | If epic_id omitted, uses 'backlog' epic. Auto-generates ID. |
| `pm_add_task(story_id, title, blocked_by?)` | `INSERT INTO tasks` | Auto-generates task ID within story |
| `pm_update_story(story_id, state?, title?, agent?, model?, write_files?, move_to_epic?, force?)` | `UPDATE stories SET ...` | Validates state transitions. Auto-sets `started_at` on →in-progress, `completed_at` on →terminal. Auto-sets `archived=1` on terminal states. |
| `pm_update_epic(epic_id, title?, state?, branch?, pr_number?, persistent?)` | `UPDATE epics SET ...` | Validates epic state transitions |
| `pm_update_task(story_id, task_id, state?, title?, force?)` | `UPDATE tasks SET ...` | Validates task state transitions |

---

## Step 6: Add analytics MCP tools (3 tools)

Pure SQL aggregation — fast and precise.

| Tool | Query | Returns |
|------|-------|---------|
| `pm_wip(epic_id?)` | `SELECT state, COUNT(*) FROM stories WHERE archived=0 GROUP BY state` | WIP by state, blocked items, agent distribution |
| `pm_cycle_time(epic_id?, since?)` | `SELECT id, started_at, completed_at FROM stories WHERE archived=1` | Per-story cycle time, averages. Returns "N/A" for stories without timestamps. |
| `pm_throughput(period?, lookback?)` | `SELECT DATE(completed_at), COUNT(*) FROM stories WHERE archived=1 GROUP BY ...` | Completed stories per period (day/week/month) |

---

## Step 7: Update consumers

### Shell scripts (use epics-cli.sh):

**`merge-latest-worktree.sh`** — Replace the inline Node.js block that reads epics.json with:
```bash
STORY_JSON=$(bash "$SCRIPTS_DIR/epics-cli.sh" "$EPICS_DB" story-by-branch "$BRANCH")
```

### Hooks (use epics-cli.sh):

**`guard-direct-edit.sh`** — Replace the Python inline that reads writeFiles with:
```bash
WRITE_FILES=$(bash "$SCRIPTS_DIR/epics-cli.sh" "$EPICS_DB" running-write-files)
```

**`load-session-context.sh`** — Replace the Python inline that reads running stories with:
```bash
RUNNING=$(bash "$SCRIPTS_DIR/epics-cli.sh" "$EPICS_DB" running-stories)
```

### Skills (use MCP tools):

**`health/SKILL.md`** — Replace "Read .claude/epics.json" with "Call `pm_list_stories` and `pm_list_epics` MCP tools"

**`deps/SKILL.md`** — Replace "Read .claude/epics.json" with "Call `pm_list_stories(include_archived=false)` grouped by epic"

**`audit/SKILL.md` + `flutter-audit/SKILL.md`** — Replace step 5 "Read .claude/epics.json" with "Call `pm_list_stories(state=...) to find open stories for cross-reference"

**`lint/SKILL.md`** — Replace "read .claude/epics.json, find the story" with "Call `pm_get_story(story_id)` to get branch"

### Agent docs:

**`todo-orchestrator.md`** — Replace "Read epics.json" with "Call `pm_search(query)` to check for duplicates"

**`epic-planner.md`** — Replace "Read epics.json" with "Call `pm_search(query)` and `pm_list_stories` for dedup"

**`git-ops.md`** — Replace update-epics.sh references with epics-cli.sh. Remove the "direct write" fallback section.

**`refs/staging-schema.md`** — Update schema reference to reflect SQLite columns instead of JSON structure.

---

## Step 8: Write tests

In `test_server.py`, following existing patterns:

- **Read tools:** Create in-memory SQLite DB with fixture data, patch `EPICS_DB`, test filtering/search
- **Write tools:** Same in-memory DB, verify INSERT/UPDATE results, test state validation
- **Analytics:** Crafted data with known timestamps, verify exact aggregations
- **State validation:** Every valid + invalid transition, `force=True` bypass
- **epics-cli.sh:** Separate bash test script with temp DB

---

## Implementation Order

1. **Database + migration** — Schema creation, `migrate-to-sqlite.sh`, `epics-cli.sh`
2. **MCP tools** — All 15 tools in server.py (helpers → reads → writes → analytics)
3. **Consumer updates** — Scripts, hooks, skills, agent docs (in dependency order)
4. **Tests** — Unit tests for MCP tools, smoke tests for epics-cli.sh
5. **Cleanup** — Delete `update-epics.sh`, `archive-closed-stories.sh`, rename/archive `epics.json`

---

## Verification

1. **Migration:** Run `migrate-to-sqlite.sh` against current `epics.json`, verify `sqlite3 epics.db "SELECT COUNT(*) FROM stories"` matches expected counts (1 active + 184 archived = 185)
2. **MCP tools:** `python -m pytest mcp-servers/gemini/test_server.py -v -k pm_`
3. **Smoke test MCP:** Start server, call `pm_board` → should show story-185 in draft column
4. **Smoke test CLI:** `bash .claude/scripts/epics-cli.sh .claude/epics.db running-stories` → should return empty or story-185
5. **Hook test:** Trigger `guard-direct-edit.sh` with a file edit, verify it queries SQLite correctly
6. **End-to-end:** Create story via `pm_create_story`, update state via `pm_update_story`, verify `pm_wip` reflects changes, verify `pm_cycle_time` captures timestamps
