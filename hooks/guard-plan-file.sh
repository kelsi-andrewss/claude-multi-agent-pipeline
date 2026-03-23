#!/bin/bash
# PreToolUse hook for mcp__gemini__pm_update_story.
# Blocks plan_file assignment when the target story has 0 tasks in epics.db.
# Belt-and-suspenders complement to the server-side check in tools_pm_write.py.
#
# Exit 0 = allow
# Exit 2 = block

source "$(dirname "$0")/lib/profile.sh"
require_profile 2

INPUT=$(cat)

STORY_ID=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('story_id',''))" 2>/dev/null)

RESULT=$(echo "$INPUT" | python3 - <<'PYEOF'
import json, sqlite3, sys, os

d = json.load(sys.stdin)
ti = d.get("tool_input", {})

plan_file = ti.get("plan_file")
story_id = ti.get("story_id")

if not plan_file or not story_id:
    print("SKIP")
    sys.exit(0)

db_path = os.path.expanduser("~/.claude/.claude/epics.db")
if not os.path.exists(db_path):
    print("SKIP")
    sys.exit(0)

try:
    conn = sqlite3.connect(db_path, timeout=5)
    count = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE story_id = ?", (story_id,)
    ).fetchone()[0]
    conn.close()
except Exception:
    print("SKIP")
    sys.exit(0)

if count == 0:
    print("BLOCK")
else:
    print("ALLOW")
PYEOF
)

case "$RESULT" in
  "BLOCK")
    echo "BLOCKED: Cannot set plan_file — story has 0 tasks. Add tasks first." >&2
    bash "$HOME/.claude/scripts/emit-event.sh" "hook.guard-plan-file" "hook" "${STORY_ID:-unknown}" "{\"reason\":\"zero-tasks\",\"result\":\"blocked\"}" || true
    exit 2
    ;;
  *)
    exit 0
    ;;
esac
