#!/bin/bash
# Stop hook — fast mtime check + background processor spawn.

source "$(dirname "$0")/lib/profile.sh"
require_profile 1

# Read stdin
INPUT=$(cat)

TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('transcript_path', ''))
" 2>/dev/null)

SESSION_ID_RAW=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('session_id', ''))
" 2>/dev/null)

CWD=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('cwd', ''))
" 2>/dev/null)

# ── Section 1: Mtime comparison (SYNC, <100ms) ──
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
SNAPSHOT="/tmp/session-mtimes-${SESSION_ID}"

OUTCOMES_CHANGED=false

if [[ -f "$SNAPSHOT" ]]; then
  source "$SNAPSHOT"

  if stat -f %m / >/dev/null 2>&1; then
    mtime() { stat -f %m "$1" 2>/dev/null || echo "0"; }
  elif stat -c %Y / >/dev/null 2>&1; then
    mtime() { stat -c %Y "$1" 2>/dev/null || echo "0"; }
  else
    mtime() { python3 -c "import os; print(int(os.path.getmtime('$1')))" 2>/dev/null || echo "0"; }
  fi

  CURRENT_OUTCOMES=$(mtime "$HOME/.claude/outcomes.md")
  [[ "$CURRENT_OUTCOMES" != "${OUTCOMES_MTIME:-0}" ]] && OUTCOMES_CHANGED=true

  if [[ "$OUTCOMES_CHANGED" == true ]]; then
    echo "outcomes.md updated"
  fi
fi

# ── Section 2: Ollama health check + warning ──
if ! curl -sf --max-time 2 http://localhost:11434/api/version > /dev/null 2>&1; then
  echo "Ollama unreachable — background learning (correction detection, session summaries) will be degraded this session."
fi

# ── Section 3: Spawn background processor ──
if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
  rm -f "$SNAPSHOT" "/tmp/session-start-${SESSION_ID}"
  exit 0
fi

DB_FILE="$HOME/.claude/.claude/epics.db"
SAFE_SESSION=$(echo "$SESSION_ID_RAW" | tr -dc 'a-zA-Z0-9')

# Skip spawn if an active process already exists for this session
PIDFILE="/tmp/stop-processor-${SAFE_SESSION}.pid"
if [[ -f "$PIDFILE" ]]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
  if kill -0 "$OLD_PID" 2>/dev/null; then
    rm -f "$SNAPSHOT" "/tmp/session-start-${SESSION_ID}"
    exit 0
  fi
fi

nohup python3 "$HOME/.claude/hooks/lib/stop_processor.py" \
  --transcript "$TRANSCRIPT_PATH" \
  --db "$DB_FILE" \
  --session "${SESSION_ID_RAW:-}" \
  --project "$HOME/.claude" \
  --cwd "${CWD:-}" \
  > "/tmp/stop-processor-${SAFE_SESSION}.log" 2>&1 &
disown

# Cleanup
rm -f "$SNAPSHOT"
rm -f "/tmp/session-start-${SESSION_ID}"
exit 0
