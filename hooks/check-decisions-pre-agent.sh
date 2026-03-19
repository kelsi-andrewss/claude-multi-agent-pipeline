#!/bin/bash
# PreToolUse hook for Agent: queries decision memory against the agent's task
# prompt. If relevant decisions exist, injects them as constraints into the
# agent's context. Blocks if the task directly names a prohibited approach.
#
# This is Gate 1: intercept before the subagent launches.

source "$(dirname "$0")/lib/profile.sh"
require_profile 1

INPUT=$(cat)

# Extract the agent prompt
PROMPT=$(echo "$INPUT" | python3 "$HOME/.claude/hooks/lib/parse_hook_input.py" prompt 2>/dev/null)
if [[ -z "$PROMPT" ]]; then
  exit 0
fi

# Skip non-coder agents (Explore, Plan, etc. don't edit files)
AGENT_TYPE=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('subagent_type',''))" 2>/dev/null)
case "$AGENT_TYPE" in
  Explore|Plan|claude-code-guide|claude-researcher|gemini-researcher|web-researcher|planner)
    exit 0
    ;;
esac

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

# Use the decisions venv Python for fastembed + sqlite-vec support
VENV_PYTHON="$HOME/.claude/mcp-servers/decisions/.venv/bin/python3"
if [[ ! -x "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

# Query decisions semantically against the task prompt (first 500 chars)
DECISIONS=$("$VENV_PYTHON" - "$PROMPT" "$PROJECT_ROOT" <<'PYEOF' 2>/dev/null
import sys, os

prompt = sys.argv[1][:500]
project_root = sys.argv[2]

# Try to use the full search engine with embeddings
sys.path.insert(0, project_root)
try:
    from pathlib import Path
    from decision_memory.store import DecisionStore
    from decision_memory.search import SearchEngine
    from decision_memory.embeddings import EmbeddingProvider

    import re
    store = DecisionStore(Path(project_root))
    store.ensure_ready()
    conn = store._get_connection()
    provider = EmbeddingProvider()
    engine = SearchEngine(conn, provider)
    # Extract key terms for search — strip noise words, limit to 8 terms
    sanitized = re.sub(r'[^\w\s]', ' ', prompt)
    stop = {'the','and','for','that','this','with','from','your','have','will',
            'are','was','been','being','would','could','should','into','also',
            'each','when','then','than','just','only','using','directly','must',
            'not','all','any','add','use','make','implement','create','write'}
    terms = [w.lower() for w in sanitized.split() if len(w) > 2 and w.lower() not in stop]
    query = ' OR '.join(terms[:8])
    results = engine.hybrid_search(query, limit=5)
    conn.close()

    if not results:
        sys.exit(0)

    for r in results:
        d = r.decision
        text = d.positive_framing or d.content
        print(f"- [decision-{d.id}] {text}")
except Exception:
    # Fallback: try raw SQLite FTS5
    import sqlite3
    db_path = os.path.join(project_root, ".claude", "decisions.db")
    if not os.path.exists(db_path):
        sys.exit(0)
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        # Extract key terms for FTS
        words = [w for w in prompt.split() if len(w) > 3][:10]
        query = " OR ".join(words)
        rows = conn.execute(
            "SELECT rowid, rank FROM decisions_fts WHERE decisions_fts MATCH ? LIMIT 5",
            (query,)
        ).fetchall()
        if not rows:
            conn.close()
            sys.exit(0)
        for rowid, rank in rows:
            row = conn.execute(
                "SELECT id, content, positive_framing FROM decisions WHERE id = ?",
                (rowid,)
            ).fetchone()
            if row:
                text = row[2] or row[1]
                print(f"- [decision-{row[0]}] {text}")
        conn.close()
    except Exception:
        sys.exit(0)
PYEOF
)

if [[ -z "$DECISIONS" ]]; then
  exit 0
fi

# BLOCK the agent launch — main session must evaluate the conflict
REASON="BLOCKED — project decisions may conflict with this task. Review before launching:
$DECISIONS

Evaluate whether the task violates any of these decisions. If compatible, retry the Agent call. If it conflicts, report the conflict to the user instead of launching."

ESCAPED=$(printf '%s' "$REASON" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))")
printf '{"decision":"block","reason":%s}' "$ESCAPED"
exit 0
