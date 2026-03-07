#!/bin/bash
# PostToolUse hook for Skill tool.
# Logs every skill invocation to tracking/skill-telemetry.jsonl.
# Exit 0 always (advisory). Async.

source "$(dirname "$0")/lib/profile.sh"
require_profile 2

INPUT=$(cat)

ENTRY=$(echo "$INPUT" | python3 -c "
import sys, json, os
from datetime import datetime, timezone

d = json.load(sys.stdin)
ti = d.get('tool_input', {})
skill = ti.get('skill', '')
if not skill:
    sys.exit(0)

entry = {
    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'date': datetime.now().strftime('%Y-%m-%d'),
    'skill': skill,
    'args': ti.get('args', ''),
    'session_id': os.environ.get('CLAUDE_SESSION_ID', 'unknown')
}
print(json.dumps(entry))
" 2>/dev/null)

if [[ -n "$ENTRY" ]]; then
  echo "$ENTRY" >> "$HOME/.claude/.claude/tracking/skill-telemetry.jsonl"
fi

exit 0
