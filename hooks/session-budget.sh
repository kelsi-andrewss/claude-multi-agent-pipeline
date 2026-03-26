#!/bin/bash
# UserPromptSubmit hook (async).
# Tracks session age by counting user prompts. At thresholds, warns about
# context fill and recommends /clear.
#
# Thresholds:
#   20 prompts — advisory: "Consider /clear if switching tasks"
#   35 prompts — warning: "Context is getting heavy. /clear recommended."
#   50 prompts — strong: "Session is deep. /clear strongly recommended to avoid degradation."
#
# Counter resets on /clear (new session).
# Exit 0 always (advisory only, async).

COUNTER_FILE="${CLAUDE_TEMP_DIR:-/tmp}/session-prompts-$$"

# Use session-scoped file. CLAUDE_SESSION_ID is set by Claude Code.
if [ -n "$CLAUDE_SESSION_ID" ]; then
  COUNTER_FILE="${CLAUDE_TEMP_DIR:-/tmp}/session-prompts-${CLAUDE_SESSION_ID}"
fi

# Read stdin (required for hook contract)
cat > /dev/null

# Increment counter
COUNT=0
if [ -f "$COUNTER_FILE" ]; then
  COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
fi
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE"

# Emit warnings at thresholds
case $COUNT in
  20)
    echo "Session depth: $COUNT prompts. Consider /clear if switching tasks." >&2
    ;;
  35)
    echo "Session depth: $COUNT prompts. Context is getting heavy — /clear recommended before starting new work." >&2
    ;;
  50)
    echo "Session depth: $COUNT prompts. Deep session — expect degraded instruction following. /clear strongly recommended." >&2
    ;;
  65|80|95)
    echo "Session depth: $COUNT prompts. Degradation likely. /clear now." >&2
    ;;
esac

exit 0
