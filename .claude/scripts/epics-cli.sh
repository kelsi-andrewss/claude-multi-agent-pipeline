#!/usr/bin/env bash
set -e

# epics-cli.sh — thin SQLite query helper for hooks and shell scripts.
# Usage: epics-cli.sh <db-path> <command> [args...]
#
# Commands:
#   story-by-branch <branch>     → JSON: {id, epicId, title, branch, writeFiles}
#   running-write-files           → JSON array of {state, writeFiles} for active stories
#   running-stories               → JSON array of {id, title, state, branch} for active stories
#   update-story <id> <json>      → Update story fields from JSON object
#   update-epic <id> <json>       → Update epic fields from JSON object
#   add-story <epic-id> <json>    → Add new story to an epic

DB_PATH="$1"
COMMAND="$2"
shift 2 || { echo "Usage: epics-cli.sh <db-path> <command> [args...]" >&2; exit 1; }

if [ ! -f "$DB_PATH" ]; then
  echo "Database not found: $DB_PATH" >&2
  exit 1
fi

case "$COMMAND" in
  story-by-branch)
    BRANCH="$1"
    if [ -z "$BRANCH" ]; then
      echo "Usage: epics-cli.sh <db> story-by-branch <branch>" >&2
      exit 1
    fi
    sqlite3 -json "$DB_PATH" \
      "SELECT s.id, s.epic_id AS epicId, s.title, s.branch, s.write_files AS writeFiles
       FROM stories s
       WHERE s.branch = '$BRANCH' AND s.archived = 0
       LIMIT 1;"
    ;;

  running-write-files)
    sqlite3 -json "$DB_PATH" \
      "SELECT s.state, s.write_files AS writeFiles
       FROM stories s
       WHERE s.state IN ('in-progress','in-review','approved')
         AND s.archived = 0;"
    ;;

  running-stories)
    sqlite3 -json "$DB_PATH" \
      "SELECT s.id, s.title, s.state, s.branch
       FROM stories s
       WHERE s.state IN ('in-progress','in-review','approved')
         AND s.archived = 0;"
    ;;

  update-story)
    STORY_ID="$1"
    JSON_FIELDS="$2"
    if [ -z "$STORY_ID" ] || [ -z "$JSON_FIELDS" ]; then
      echo "Usage: epics-cli.sh <db> update-story <story-id> '<json-fields>'" >&2
      exit 1
    fi
    # Build SET clause from JSON keys
    python3 -c "
import json, sqlite3, sys

story_id = sys.argv[1]
fields = json.loads(sys.argv[2])
db_path = sys.argv[3]

# Map camelCase field names to snake_case column names
FIELD_MAP = {
    'state': 'state', 'title': 'title', 'branch': 'branch',
    'writeFiles': 'write_files', 'write_files': 'write_files',
    'needsTesting': 'needs_testing', 'needs_testing': 'needs_testing',
    'needsReview': 'needs_review', 'needs_review': 'needs_review',
    'agent': 'agent', 'model': 'model',
    'dependsOn': 'depends_on', 'depends_on': 'depends_on',
    'autoMerge': 'auto_merge', 'auto_merge': 'auto_merge',
    'epicId': 'epic_id', 'epic_id': 'epic_id',
    'startedAt': 'started_at', 'started_at': 'started_at',
    'completedAt': 'completed_at', 'completed_at': 'completed_at',
    'archived': 'archived',
}

sets = []
vals = []
for k, v in fields.items():
    col = FIELD_MAP.get(k)
    if not col:
        print(f'Unknown field: {k}', file=sys.stderr)
        sys.exit(1)
    if isinstance(v, (list, dict)):
        v = json.dumps(v)
    sets.append(f'{col} = ?')
    vals.append(v)

if not sets:
    sys.exit(0)

vals.append(story_id)
conn = sqlite3.connect(db_path)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute(f'UPDATE stories SET {\", \".join(sets)} WHERE id = ?', vals)
conn.commit()
conn.close()
" "$STORY_ID" "$JSON_FIELDS" "$DB_PATH"
    ;;

  update-epic)
    EPIC_ID="$1"
    JSON_FIELDS="$2"
    if [ -z "$EPIC_ID" ] || [ -z "$JSON_FIELDS" ]; then
      echo "Usage: epics-cli.sh <db> update-epic <epic-id> '<json-fields>'" >&2
      exit 1
    fi
    python3 -c "
import json, sqlite3, sys

epic_id = sys.argv[1]
fields = json.loads(sys.argv[2])
db_path = sys.argv[3]

FIELD_MAP = {
    'title': 'title', 'branch': 'branch', 'state': 'state',
    'prNumber': 'pr_number', 'pr_number': 'pr_number',
    'persistent': 'persistent',
}

sets = []
vals = []
for k, v in fields.items():
    col = FIELD_MAP.get(k)
    if not col:
        print(f'Unknown field: {k}', file=sys.stderr)
        sys.exit(1)
    sets.append(f'{col} = ?')
    vals.append(v)

if not sets:
    sys.exit(0)

vals.append(epic_id)
conn = sqlite3.connect(db_path)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute(f'UPDATE epics SET {\", \".join(sets)} WHERE id = ?', vals)
conn.commit()
conn.close()
" "$EPIC_ID" "$JSON_FIELDS" "$DB_PATH"
    ;;

  add-story)
    EPIC_ID="$1"
    JSON_STORY="$2"
    if [ -z "$EPIC_ID" ] || [ -z "$JSON_STORY" ]; then
      echo "Usage: epics-cli.sh <db> add-story <epic-id> '<json-story>'" >&2
      exit 1
    fi
    python3 -c "
import json, sqlite3, sys

epic_id = sys.argv[1]
story = json.loads(sys.argv[2])
db_path = sys.argv[3]

conn = sqlite3.connect(db_path)
conn.execute('PRAGMA journal_mode=WAL')

# Auto-generate ID if not provided
if 'id' not in story:
    row = conn.execute('SELECT MAX(CAST(SUBSTR(id, 7) AS INTEGER)) FROM stories').fetchone()
    next_num = (row[0] or 0) + 1
    story['id'] = f'story-{next_num}'

conn.execute('''
    INSERT INTO stories (id, epic_id, title, state, branch, write_files,
        needs_testing, needs_review, agent, model, depends_on, auto_merge)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''', (
    story['id'],
    epic_id,
    story.get('title', ''),
    story.get('state', 'draft'),
    story.get('branch'),
    json.dumps(story.get('writeFiles', story.get('write_files', []))),
    int(story.get('needsTesting', story.get('needs_testing', 0))),
    int(story.get('needsReview', story.get('needs_review', 0))),
    story.get('agent'),
    story.get('model'),
    json.dumps(story.get('dependsOn', story.get('depends_on', []))),
    int(story.get('autoMerge', story.get('auto_merge', 0))),
))

# Insert tasks if present
for task in story.get('tasks', []):
    conn.execute('''
        INSERT INTO tasks (id, story_id, title, state, blocked_by)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        task['id'],
        story['id'],
        task.get('title', ''),
        task.get('state', 'todo'),
        task.get('blockedBy', task.get('blocked_by')),
    ))

conn.commit()
print(story['id'])
conn.close()
" "$EPIC_ID" "$JSON_STORY" "$DB_PATH"
    ;;

  *)
    echo "Unknown command: $COMMAND" >&2
    echo "Valid commands: story-by-branch, running-write-files, running-stories, update-story, update-epic, add-story" >&2
    exit 1
    ;;
esac
