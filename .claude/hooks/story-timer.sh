#!/bin/bash
set -e

# Per-story time tracking hook.
# Usage:
#   story-timer.sh start <story-id> [title]
#   story-timer.sh stop  <story-id> [title]
#
# On start: writes a temp file with the epoch start time.
# On stop:  reads the temp file, computes duration, appends a row to story-times.md.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACKING_FILE="$SCRIPT_DIR/../tracking/story-times.md"
TMPDIR_BASE="/tmp/story-timer"

ACTION="${1:-}"
STORY_ID="${2:-}"
TITLE="${3:-}"

if [[ -z "$ACTION" || -z "$STORY_ID" ]]; then
    echo "Usage: story-timer.sh start|stop <story-id> [title]" >&2
    exit 1
fi

mkdir -p "$TMPDIR_BASE"

case "$ACTION" in
    start)
        START_TS=$(date +%s)
        echo "$START_TS" > "$TMPDIR_BASE/$STORY_ID.start"
        echo "Timer started for $STORY_ID at $START_TS"
        ;;

    stop)
        START_FILE="$TMPDIR_BASE/$STORY_ID.start"
        if [[ ! -f "$START_FILE" ]]; then
            echo "No start time found for $STORY_ID — skipping duration calc" >&2
            exit 0
        fi

        START_TS=$(cat "$START_FILE")
        END_TS=$(date +%s)
        DURATION_SECS=$(( END_TS - START_TS ))
        DURATION_MINS=$(( DURATION_SECS / 60 ))

        START_HUMAN=$(date -r "$START_TS" "+%Y-%m-%d %H:%M" 2>/dev/null || date -d "@$START_TS" "+%Y-%m-%d %H:%M")
        END_HUMAN=$(date -r "$END_TS" "+%Y-%m-%d %H:%M" 2>/dev/null || date -d "@$END_TS" "+%Y-%m-%d %H:%M")

        TITLE_COL="${TITLE:-(no title)}"

        echo "| $STORY_ID | $TITLE_COL | $START_HUMAN | $END_HUMAN | $DURATION_MINS |" >> "$TRACKING_FILE"

        rm -f "$START_FILE"
        echo "Timer stopped for $STORY_ID: ${DURATION_MINS}m"
        ;;

    *)
        echo "Unknown action: $ACTION. Use start or stop." >&2
        exit 1
        ;;
esac

exit 0
