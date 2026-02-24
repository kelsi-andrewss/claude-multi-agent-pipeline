#!/bin/bash
# PostToolUse hook for story time tracking.
# Detects update-epics.sh calls that transition a story to 'running' or 'closed'.
# On 'running': writes epoch start time to /tmp/story-timer-<id>-start
# On 'closed': reads start time, computes duration, appends to story-times.md
#
# Exit 0 always (advisory only).

INPUT=$(cat)

# Extract the command string from tool_input
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('command', ''))
" 2>/dev/null)

# Only process update-epics.sh commands
if [[ ! "$COMMAND" =~ update-epics\.sh ]]; then
  exit 0
fi

# Extract the JSON patch from the command string using python3
# The patch is typically passed as an argument, e.g.: update-epics.sh '{"storyId":"...", "fields":{"state":"..."}}'
PATCH=$(echo "$INPUT" | python3 -c "
import sys, json, re, shlex
d = json.load(sys.stdin)
cmd = d.get('tool_input', {}).get('command', '')

# Find quoted JSON in the command (common pattern: update-epics.sh '...')
# Look for the pattern: update-epics.sh followed by a quoted string
match = re.search(r\"update-epics\.sh\s+'({[^}]+})'\", cmd)
if match:
    try:
        patch = json.loads(match.group(1))
        print(json.dumps(patch))
    except:
        pass
" 2>/dev/null)

# If no patch was found, exit gracefully
if [[ -z "$PATCH" ]]; then
  exit 0
fi

# Parse the patch to extract storyId and state
STORY_ID=$(echo "$PATCH" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('storyId', ''))" 2>/dev/null)
STATE=$(echo "$PATCH" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('fields', {}).get('state', ''))" 2>/dev/null)

# Exit if we couldn't extract required fields
if [[ -z "$STORY_ID" ]] || [[ -z "$STATE" ]]; then
  exit 0
fi

TIMER_FILE="/tmp/story-timer-${STORY_ID}-start"

# Handle 'running' state: write epoch seconds
if [[ "$STATE" == "running" ]]; then
  date +%s > "$TIMER_FILE"
  exit 0
fi

# Handle 'closed' state: compute duration and append to tracking file
if [[ "$STATE" == "closed" ]]; then
  # Exit if start file doesn't exist (session may have started mid-story)
  if [[ ! -f "$TIMER_FILE" ]]; then
    exit 0
  fi

  # Read start time and compute duration
  START_EPOCH=$(cat "$TIMER_FILE" 2>/dev/null)
  END_EPOCH=$(date +%s)
  DURATION_SECS=$((END_EPOCH - START_EPOCH))
  DURATION_MINS=$(printf "%.1f" $(echo "scale=1; $DURATION_SECS / 60" | bc))

  # Look up story title from epics.json
  EPICS_FILE="$HOME/.claude/.claude/epics.json"
  if [[ ! -f "$EPICS_FILE" ]]; then
    rm -f "$TIMER_FILE"
    exit 0
  fi

  TITLE=$(python3 -c "
import sys, json
try:
    with open('$EPICS_FILE', 'r') as f:
        data = json.load(f)
    for epic in data.get('epics', []):
        for story in epic.get('stories', []):
            if story.get('id') == '$STORY_ID':
                print(story.get('title', 'Unknown'))
                sys.exit(0)
except:
    pass
print('Unknown')
" 2>/dev/null)

  # Extract agent and model from environment
  AGENT="${AGENT_NAME:-unknown}"
  MODEL="${AGENT_MODEL:-unknown}"

  # Format date as YYYY-MM-DD
  DATE=$(date +%Y-%m-%d)

  # Build tracking file path
  TRACKING_FILE="$HOME/.claude/.claude/tracking/story-times.md"

  # Append row to tracking file
  if [[ -f "$TRACKING_FILE" ]]; then
    echo "| $STORY_ID | $TITLE | $DURATION_MINS | $AGENT | $MODEL | $DATE |" >> "$TRACKING_FILE"
  fi

  # Clean up timer file
  rm -f "$TIMER_FILE"

  exit 0
fi

exit 0
