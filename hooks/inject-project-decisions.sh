#!/bin/bash
# PreToolUse hook: injects relevant project decisions before Edit/Write/MultiEdit.
# Queries the local decision store for decisions scoped to the file being edited.
# Always exits 0 — injection hooks never block tool execution.

source "$(dirname "$0")/lib/profile.sh"
require_profile 1

INPUT=$(cat)

# Extract file path from tool input
FILE_PATH=$(echo "$INPUT" | python3 "$HOME/.claude/hooks/lib/parse_hook_input.py" file_path 2>/dev/null)
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Session injection cap — max 5 per session
COUNTER_FILE="$CLAUDE_TEMP_DIR/decision-inject-count-${SESSION_ID}"
COUNT=0
if [[ -f "$COUNTER_FILE" ]]; then
  COUNT=$(cat "$COUNTER_FILE" 2>/dev/null)
  COUNT=${COUNT:-0}
fi
if (( COUNT >= 5 )); then
  exit 0
fi

# Per-file dedup — skip if already injected for this exact path
DEDUP_FILE="$CLAUDE_TEMP_DIR/decision-inject-files-${SESSION_ID}"
if [[ -f "$DEDUP_FILE" ]] && grep -qxF "$FILE_PATH" "$DEDUP_FILE" 2>/dev/null; then
  exit 0
fi

# Walk up from FILE_PATH to find .git/ directory (project root)
PROJECT_ROOT=""
DIR=$(dirname "$FILE_PATH")
while [[ "$DIR" != "/" ]]; do
  if [[ -d "$DIR/.git" ]]; then
    PROJECT_ROOT="$DIR"
    break
  fi
  DIR=$(dirname "$DIR")
done
if [[ -z "$PROJECT_ROOT" ]]; then
  exit 0
fi

# Query decisions scoped to this file, apply freshness tiers
DECISIONS=$(python3 - "$FILE_PATH" "$PROJECT_ROOT" <<'PYEOF' 2>/dev/null
import sys, sqlite3, os

file_path = sys.argv[1]
project_root = sys.argv[2]

db_path = os.path.join(project_root, ".claude", "decisions.db")
sql_path = os.path.join(project_root, ".claude", "decisions.sql")

db = None
if os.path.exists(db_path):
    db = sqlite3.connect(db_path, timeout=2)
elif os.path.exists(sql_path):
    content = open(sql_path, encoding="utf-8").read().strip()
    if not content:
        sys.exit(0)
    db = sqlite3.connect(":memory:")
    db.executescript(content)

if not db:
    sys.exit(0)

try:
    cursor = db.execute("""
        SELECT DISTINCT d.id, d.content
        FROM decisions d
        LEFT JOIN decision_scopes ds ON d.id = ds.decision_id
        WHERE d.status = 'active'
          AND (ds.scope_value IS NULL
               OR ? LIKE '%' || ds.scope_value || '%'
               OR ds.scope_value LIKE '%' || ? || '%')
        LIMIT 5
    """, (file_path, os.path.basename(file_path)))
    rows = cursor.fetchall()
except Exception:
    db.close()
    sys.exit(0)

db.close()

if not rows:
    sys.exit(0)

# Load freshness scores from run-state.db
scores = {}
run_state_path = os.path.join(os.path.expanduser("~"), ".claude", ".claude", "run-state.db")
if os.path.exists(run_state_path):
    try:
        rdb = sqlite3.connect(run_state_path, timeout=2)
        ids = [str(r[0]) for r in rows]
        placeholders = ",".join("?" * len(ids))
        for rid, score in rdb.execute(
            f"SELECT decision_id, staleness_score FROM decision_freshness WHERE decision_id IN ({placeholders})",
            ids
        ):
            scores[rid] = score
        rdb.close()
    except Exception:
        pass

def one_line(text):
    first = text.split(". ")[0].split(" — ")[-1].strip()
    if not first.endswith("."):
        first += "."
    return first

for did, content in rows:
    staleness = scores.get(did)
    if staleness is None or staleness < 0.3:
        print(f"[decision-{did}] {content}")
    elif staleness <= 0.7:
        print(f"[decision-{did}] {one_line(content)}")
    else:
        print(f"[STALE] [decision-{did}] {one_line(content)}")
PYEOF
)

if [[ -z "$DECISIONS" ]]; then
  exit 0
fi

# Record dedup and increment counter
echo "$FILE_PATH" >> "$DEDUP_FILE"
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE"

# Build and output injection JSON
CONTEXT="=== PROJECT DECISIONS (auto-injected for $(basename "$FILE_PATH")) ==="$'\n'"$DECISIONS"
ESCAPED=$(printf '%s' "$CONTEXT" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))")
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":%s}}' "$ESCAPED"
exit 0
