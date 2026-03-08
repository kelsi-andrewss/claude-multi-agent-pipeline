# Staging Payload Schema

## Backend

The tracking system uses a SQLite database at `.claude/epics.db` (WAL mode).
All queries and mutations go through either:
- **MCP tools** (`pm_*`) — used by Claude agents and skills
- **epics-cli.sh** — used by shell scripts and hooks

## Database schema

```sql
CREATE TABLE epics (
  id         TEXT PRIMARY KEY,  -- "epic-022"
  title      TEXT NOT NULL,
  branch     TEXT,              -- "epic/022"
  pr_number  INTEGER,
  persistent INTEGER DEFAULT 0,
  state      TEXT DEFAULT 'active' CHECK(state IN ('active','done','shipped'))
);

CREATE TABLE stories (
  id             TEXT PRIMARY KEY,  -- "story-185"
  epic_id        TEXT NOT NULL REFERENCES epics(id),
  title          TEXT NOT NULL,
  state          TEXT DEFAULT 'draft',
  branch         TEXT,
  write_files    TEXT,              -- JSON array
  needs_testing  INTEGER DEFAULT 0,
  needs_review   INTEGER DEFAULT 0,
  agent          TEXT,
  model          TEXT,
  depends_on     TEXT,              -- JSON array
  auto_merge     INTEGER DEFAULT 0,
  started_at     TEXT,              -- ISO 8601
  completed_at   TEXT,              -- ISO 8601
  archived       INTEGER DEFAULT 0
);

CREATE TABLE tasks (
  id         TEXT NOT NULL,        -- "t1"
  story_id   TEXT NOT NULL REFERENCES stories(id),
  title      TEXT NOT NULL,
  state      TEXT DEFAULT 'todo' CHECK(state IN ('todo','in-progress','done','blocked','skipped')),
  blocked_by TEXT,
  PRIMARY KEY (story_id, id)
);
```

## Payload structure

Staging payloads are still JSON files written to `$TMPDIR/staging-<slug>.json`:

```json
{
  "storyUpdate": {
    "id": "story-001",
    "epicId": "epic-001",
    "title": "Story title",
    "state": "draft",
    "branch": null,
    "writeFiles": ["src/handlers/stageHandlers.js"],
    "needsTesting": false,
    "needsReview": false,
    "agent": "quick-fixer",
    "model": "sonnet",
    "tasks": []
  },
  "epicUpdate": {
    "id": "epic-001",
    "title": "Epic title",
    "branch": null,
    "prNumber": null,
    "persistent": true,
    "state": "active"
  }
}
```

`epicUpdate` is null if no new epic is needed.

After validation, the main session applies the payload via `pm_create_story` / `pm_create_epic` / `pm_update_story` MCP tools.

## Required fields

**storyUpdate** (all required): `id`, `epicId`, `title`, `state`, `branch`, `writeFiles`, `needsTesting`, `needsReview`

Optional: `agent`, `model`, `tasks`, `dependsOn`, `autoMerge`

**epicUpdate** (all required if present): `id`, `title`, `branch`, `prNumber`, `persistent`, `state`

## Validation rules

- `state` must be a valid story state: `draft`, `ready`, `in-progress`, `in-review`, `approved`, `done`, `blocked`, `shipped`
- Epic `state` must be: `active`, `done`, `shipped`
- `writeFiles` must be a non-empty array
- If `epicUpdate` is present: all required fields must be present
- If validation fails: surface the error to the user, do not write, do not re-launch orchestrator

## Story state transitions

```
draft → ready             (run trigger, dependencies met)
draft → in-progress       (coder launched directly)
ready → in-progress       (coder launched)
in-progress → in-review   (coder done, testing or review needed)
in-progress → approved    (coder done, no testing/review needed)
in-progress → done        (completed)
in-progress → blocked     (stuck)
in-review → in-progress   (test/review failed, send back to coder)
in-review → approved      (test/review passed)
approved → done           (merged into epic branch)
approved → shipped        (fast-track)
done → shipped            (epic dev branch merged to dev)
any → blocked             (stuck)
blocked → in-progress     (manual reset)
any → draft               (rescoped — pulled back to planning)
```

## Epic state transitions

```
active → done             (all stories done, PR ready)
done → shipped            (merged to dev)
done → active             (reopened)
```

## Task sub-item schema

```sql
-- Tasks are rows in the tasks table, keyed by (story_id, id)
-- States: todo, in-progress, done, blocked, skipped
-- blocked_by: references another task ID within the same story
```

Task states: `todo`, `in-progress`, `done`, `blocked`, `skipped`.

## Backlog epic

```sql
-- Auto-created on first use via pm_create_story with no epic_id
INSERT INTO epics (id, title, persistent, state)
VALUES ('epic-backlog', 'Backlog', 1, 'active');
```

## State migration (historical)

Old state names were migrated to new names during the JSON→SQLite migration:

| Old | New |
|---|---|
| `filling` | `draft` |
| `queued` | `ready` |
| `running` | `in-progress` |
| `testing` | `in-review` |
| `reviewing` | `in-review` |
| `merging` | `approved` |
| `closed` | `done` |
