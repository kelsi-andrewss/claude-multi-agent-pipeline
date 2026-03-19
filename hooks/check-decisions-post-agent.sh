#!/bin/bash
# PostToolUse hook for Agent: after a coder returns, check if it changed files
# that have decision constraints. Surfaces violations so the main session can
# catch them before merging.
#
# This is Gate 2: intercept after the subagent returns.

source "$(dirname "$0")/lib/profile.sh"
require_profile 1

INPUT=$(cat)

# Skip non-coder agents
AGENT_TYPE=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('subagent_type',''))" 2>/dev/null)
case "$AGENT_TYPE" in
  Explore|Plan|claude-code-guide|claude-researcher|gemini-researcher|web-researcher|planner)
    exit 0
    ;;
esac

# Extract the agent result to find changed files
# The result contains worktreePath and worktreeBranch if files were changed
RESULT=$(echo "$INPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
resp = d.get('tool_response', '')
if isinstance(resp, dict):
    print(json.dumps(resp))
else:
    print(resp)
" 2>/dev/null)

# Try to extract worktree path from the result
WORKTREE_PATH=$(echo "$RESULT" | python3 -c "
import json, sys, re
text = sys.stdin.read()
# Try JSON parse
try:
    d = json.loads(text)
    print(d.get('worktreePath', ''))
    sys.exit(0)
except Exception:
    pass
# Try regex extraction from text
m = re.search(r'worktreePath:\s*(\S+)', text)
if m:
    print(m.group(1))
else:
    # No worktree = no file changes
    pass
" 2>/dev/null)

if [[ -z "$WORKTREE_PATH" || ! -d "$WORKTREE_PATH" ]]; then
  exit 0
fi

# Find project root
PROJECT_ROOT=""
CWD=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null)
DIR="${CWD:-$PWD}"
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

# Get list of changed files in the worktree
CHANGED_FILES=$(git -C "$WORKTREE_PATH" diff --name-only HEAD~1 HEAD 2>/dev/null)
if [[ -z "$CHANGED_FILES" ]]; then
  # Try against dev branch
  CHANGED_FILES=$(git -C "$WORKTREE_PATH" diff --name-only origin/dev...HEAD 2>/dev/null)
fi
if [[ -z "$CHANGED_FILES" ]]; then
  exit 0
fi

# Use the decisions venv Python for fastembed + sqlite-vec support
VENV_PYTHON="$HOME/.claude/mcp-servers/decisions/.venv/bin/python3"
if [[ ! -x "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

# Query decisions for each changed file
VIOLATIONS=$("$VENV_PYTHON" - "$PROJECT_ROOT" "$CHANGED_FILES" <<'PYEOF' 2>/dev/null
import sys, sqlite3, os

project_root = sys.argv[1]
changed_files = sys.argv[2].strip().split('\n')

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

found = []
seen = set()
for f in changed_files:
    f = f.strip()
    if not f:
        continue
    basename = os.path.basename(f)
    try:
        rows = db.execute("""
            SELECT DISTINCT d.id, COALESCE(d.positive_framing, d.content)
            FROM decisions d
            LEFT JOIN decision_scopes ds ON d.id = ds.decision_id
            WHERE d.status = 'active'
              AND (ds.scope_value IS NULL
                   OR ? LIKE '%' || ds.scope_value || '%'
                   OR ds.scope_value LIKE '%' || ? || '%')
            LIMIT 3
        """, (f, basename)).fetchall()
        for did, content in rows:
            if did not in seen:
                found.append(f"- [decision-{did}] (file: {basename}) {content}")
                seen.add(did)
    except Exception:
        pass

db.close()

if not found:
    sys.exit(0)

for line in found:
    print(line)
PYEOF
)

if [[ -z "$VIOLATIONS" ]]; then
  exit 0
fi

# Surface as context — main session should review before merging
CONTEXT="⚠️ DECISION CHECK — The coder agent modified files with active decision constraints. Review these before merging:
$VIOLATIONS

Verify the changes are compatible with these decisions before proceeding with merge."

ESCAPED=$(printf '%s' "$CONTEXT" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))")
printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s}}' "$ESCAPED"
exit 0
