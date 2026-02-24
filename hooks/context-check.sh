#!/bin/bash
# PostToolUse hook for TaskUpdate.
# Tracks completed stories in a per-session counter. When 3+ stories
# have been closed in a single session, prints the standardized clearing
# message so the user knows it's time to /clear.
#
# Counter file: /tmp/stories-closed-${SESSION_ID}
# Exit 0 always (advisory only).

INPUT=$(cat)

# Extract the status field from the TaskUpdate tool input
STATUS=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('status', ''))
" 2>/dev/null)

# Only count completions
if [[ "$STATUS" != "completed" ]]; then
  exit 0
fi

# Use a session ID based on the parent PID chain (stable within a session)
SESSION_ID="${PPID:-$$}"
COUNTER_FILE="/tmp/stories-closed-${SESSION_ID}"

# Increment counter
COUNT=0
if [[ -f "$COUNTER_FILE" ]]; then
  COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
fi
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE"

# Emit clearing message when threshold is reached
if [[ "$COUNT" -ge 3 ]]; then
  echo "" >&2
  echo "Context checkpoint reached (3 stories closed this session). Run \`/clear\` to reset the session. All epic and story state is saved in epics.json." >&2
fi

exit 0
