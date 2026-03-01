#!/usr/bin/env bash
set -e

# migrate-to-sqlite.sh — One-time migration from epics.json → epics.db
# Usage: migrate-to-sqlite.sh [project-root]
#
# Creates .claude/epics.db with the full schema and migrates all data
# from .claude/epics.json. Renames epics.json → epics.json.bak after success.

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
EPICS_JSON="${PROJECT_ROOT}/.claude/epics.json"
EPICS_DB="${PROJECT_ROOT}/.claude/epics.db"

if [ ! -f "$EPICS_JSON" ]; then
  echo "epics.json not found at ${EPICS_JSON}" >&2
  exit 1
fi

if [ -f "$EPICS_DB" ]; then
  echo "epics.db already exists at ${EPICS_DB}. Remove it first to re-migrate." >&2
  exit 1
fi

python3 -c "
import json, sqlite3, sys
from datetime import datetime

epics_json = sys.argv[1]
epics_db = sys.argv[2]

with open(epics_json) as f:
    data = json.load(f)

conn = sqlite3.connect(epics_db)
conn.execute('PRAGMA journal_mode=WAL')

# Create schema
conn.executescript('''
CREATE TABLE epics (
  id         TEXT PRIMARY KEY,
  title      TEXT NOT NULL,
  branch     TEXT,
  pr_number  INTEGER,
  persistent INTEGER DEFAULT 0,
  state      TEXT DEFAULT \"active\" CHECK(state IN (\"active\",\"done\",\"shipped\"))
);

CREATE TABLE stories (
  id             TEXT PRIMARY KEY,
  epic_id        TEXT NOT NULL REFERENCES epics(id),
  title          TEXT NOT NULL,
  state          TEXT DEFAULT \"draft\",
  branch         TEXT,
  write_files    TEXT,
  needs_testing  INTEGER DEFAULT 0,
  needs_review   INTEGER DEFAULT 0,
  agent          TEXT,
  model          TEXT,
  depends_on     TEXT,
  auto_merge     INTEGER DEFAULT 0,
  started_at     TEXT,
  completed_at   TEXT,
  archived       INTEGER DEFAULT 0
);

CREATE TABLE tasks (
  id         TEXT NOT NULL,
  story_id   TEXT NOT NULL REFERENCES stories(id),
  title      TEXT NOT NULL,
  state      TEXT DEFAULT \"todo\" CHECK(state IN (\"todo\",\"in-progress\",\"done\",\"blocked\",\"skipped\")),
  blocked_by TEXT,
  PRIMARY KEY (story_id, id)
);

CREATE INDEX idx_stories_state ON stories(state) WHERE archived = 0;
CREATE INDEX idx_stories_epic ON stories(epic_id) WHERE archived = 0;
CREATE INDEX idx_stories_branch ON stories(branch) WHERE branch IS NOT NULL;
''')

# State migration map (old → new)
STATE_MAP = {
    'filling': 'draft',
    'queued': 'ready',
    'running': 'in-progress',
    'testing': 'in-review',
    'reviewing': 'in-review',
    'merging': 'approved',
    'closed': 'done',
}

def migrate_state(state):
    return STATE_MAP.get(state, state)

epic_count = 0
story_count = 0
task_count = 0
archive_count = 0

# Migrate epics and their stories
for epic in data.get('epics', []):
    epic_id = epic['id']
    conn.execute('''
        INSERT INTO epics (id, title, branch, pr_number, persistent, state)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        epic_id,
        epic.get('title', ''),
        epic.get('branch'),
        epic.get('prNumber'),
        int(epic.get('persistent', False)),
        epic.get('state', 'active'),
    ))
    epic_count += 1

    for story in epic.get('stories', []):
        state = migrate_state(story.get('state', 'draft'))
        write_files = story.get('writeFiles', [])
        depends_on = story.get('dependsOn', [])
        conn.execute('''
            INSERT INTO stories (id, epic_id, title, state, branch, write_files,
                needs_testing, needs_review, agent, model, depends_on, auto_merge,
                started_at, completed_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ''', (
            story['id'],
            story.get('epicId', epic_id),
            story.get('title', ''),
            state,
            story.get('branch'),
            json.dumps(write_files) if write_files else '[]',
            int(story.get('needsTesting', False)),
            int(story.get('needsReview', False)),
            story.get('agent'),
            story.get('model'),
            json.dumps(depends_on) if depends_on else '[]',
            int(story.get('autoMerge', False)),
            story.get('startedAt'),
            story.get('completedAt'),
        ))
        story_count += 1

        for task in story.get('tasks', []):
            conn.execute('''
                INSERT INTO tasks (id, story_id, title, state, blocked_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                task['id'],
                story['id'],
                task.get('title', ''),
                task.get('state', 'todo'),
                task.get('blockedBy'),
            ))
            task_count += 1

# Migrate backlog stories
backlog = data.get('backlog', [])
if backlog:
    # Create backlog epic if it doesn't exist
    conn.execute('''
        INSERT OR IGNORE INTO epics (id, title, persistent, state)
        VALUES ('epic-backlog', 'Backlog', 1, 'active')
    ''')

    for story in backlog:
        state = migrate_state(story.get('state', 'draft'))
        write_files = story.get('writeFiles', [])
        depends_on = story.get('dependsOn', [])
        conn.execute('''
            INSERT INTO stories (id, epic_id, title, state, branch, write_files,
                needs_testing, needs_review, agent, model, depends_on, auto_merge,
                started_at, completed_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ''', (
            story['id'],
            story.get('epicId', 'epic-backlog'),
            story.get('title', ''),
            state,
            story.get('branch'),
            json.dumps(write_files) if write_files else '[]',
            int(story.get('needsTesting', False)),
            int(story.get('needsReview', False)),
            story.get('agent'),
            story.get('model'),
            json.dumps(depends_on) if depends_on else '[]',
            int(story.get('autoMerge', False)),
            story.get('startedAt'),
            story.get('completedAt'),
        ))
        story_count += 1

# Migrate archive
for story in data.get('archive', []):
    state = migrate_state(story.get('state', 'done'))
    epic_id = story.get('epicId', 'epic-backlog')

    # Ensure the epic exists (archived stories may reference old epics)
    conn.execute('''
        INSERT OR IGNORE INTO epics (id, title, persistent, state)
        VALUES (?, ?, 0, 'done')
    ''', (epic_id, f'Epic {epic_id}'))

    write_files = story.get('writeFiles', [])
    depends_on = story.get('dependsOn', [])
    conn.execute('''
        INSERT OR IGNORE INTO stories (id, epic_id, title, state, branch, write_files,
            needs_testing, needs_review, agent, model, depends_on, auto_merge,
            started_at, completed_at, archived)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    ''', (
        story['id'],
        epic_id,
        story.get('title', ''),
        state,
        story.get('branch'),
        json.dumps(write_files) if write_files else '[]',
        int(story.get('needsTesting', False)),
        int(story.get('needsReview', False)),
        story.get('agent'),
        story.get('model'),
        json.dumps(depends_on) if depends_on else '[]',
        int(story.get('autoMerge', False)),
        story.get('startedAt'),
        story.get('completedAt'),
    ))
    archive_count += 1

conn.commit()
conn.close()

print(f'Migration complete:')
print(f'  Epics:           {epic_count}')
print(f'  Active stories:  {story_count}')
print(f'  Archived stories:{archive_count}')
print(f'  Tasks:           {task_count}')
print(f'  Database:        {epics_db}')
" "$EPICS_JSON" "$EPICS_DB"

# Rename original file as backup
mv "$EPICS_JSON" "${EPICS_JSON}.bak"
echo ""
echo "Renamed ${EPICS_JSON} → ${EPICS_JSON}.bak"
echo "Migration successful. You can delete the .bak file after verifying."
