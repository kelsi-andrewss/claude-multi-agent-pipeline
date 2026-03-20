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

# ── Section 1: Check for new outcomes since session start (SYNC, <100ms) ──
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')

OUTCOMES_CHANGED=false
RUN_STATE_DB="$HOME/.claude/.claude/run-state.db"
SESSION_START_FILE="$CLAUDE_TEMP_DIR/session-start-${SESSION_ID}"

if [[ -f "$RUN_STATE_DB" && -f "$SESSION_START_FILE" ]]; then
  SESSION_START_EPOCH=$(cat "$SESSION_START_FILE")
  NEW_OUTCOMES=$(sqlite3 "$RUN_STATE_DB" \
    "SELECT count(*) FROM merge_outcomes WHERE created_at > datetime($SESSION_START_EPOCH, 'unixepoch');" \
    2>/dev/null || echo "0")
  if [[ "$NEW_OUTCOMES" -gt 0 ]]; then
    OUTCOMES_CHANGED=true
    echo "outcomes updated ($NEW_OUTCOMES new since session start)"
  fi
fi

# ── Section 2: Ollama health check + warning ──
if ! curl -sf --max-time 2 http://localhost:11434/api/version > /dev/null 2>&1; then
  echo "Ollama unreachable — background learning (correction detection, session summaries) will be degraded this session."
fi

# ── Section 3: Spawn background processor ──
if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
  rm -f "$CLAUDE_TEMP_DIR/session-start-${SESSION_ID}"
  exit 0
fi

DB_FILE="$HOME/.claude/.claude/epics.db"
SAFE_SESSION=$(echo "$SESSION_ID_RAW" | tr -dc 'a-zA-Z0-9')

# Skip spawn if an active process already exists for this session
PIDFILE="$CLAUDE_TEMP_DIR/stop-processor-${SAFE_SESSION}.pid"
if [[ -f "$PIDFILE" ]]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
  if kill -0 "$OLD_PID" 2>/dev/null; then
    rm -f "$CLAUDE_TEMP_DIR/session-start-${SESSION_ID}"
    exit 0
  fi
fi

nohup python3 "$HOME/.claude/hooks/lib/stop_processor.py" \
  --transcript "$TRANSCRIPT_PATH" \
  --db "$DB_FILE" \
  --session "${SESSION_ID_RAW:-}" \
  --project "$HOME/.claude" \
  --cwd "${CWD:-}" \
  > "$CLAUDE_TEMP_DIR/stop-processor-${SAFE_SESSION}.log" 2>&1 &
disown
bash "$HOME/.claude/scripts/emit-event.sh" "hook.session-learning-check" "hook" "${SESSION_ID_RAW:-unknown}" "{\"action\":\"processor-spawned\",\"result\":\"logged\"}" || true

# Cleanup
rm -f "$CLAUDE_TEMP_DIR/session-start-${SESSION_ID}"
exit 0
