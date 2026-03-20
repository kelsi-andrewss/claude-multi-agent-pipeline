#!/bin/bash
# PostToolUse hook for Skill tool.
# Logs every skill invocation to tracking/skill-telemetry.jsonl.
# Exit 0 always (advisory). Async.

source "$(dirname "$0")/lib/profile.sh"
require_profile 2
source "$(dirname "$0")/lib/log_rotator.sh"

INPUT=$(cat)

ENTRY=$(echo "$INPUT" | python3 -c "
import sys, json, os, re
from datetime import datetime, timezone

def scrub_credentials(text):
    patterns = [
        (r'(Bearer\s+)\S+', r'\1[REDACTED]'),
        (r'(Authorization[=:]\s*)\S+', r'\1[REDACTED]'),
        (r'(sk-|ak-|key-|ghp_|gho_|ghu_|ghs_|ghr_)\S+', '[REDACTED]'),
        (r'AIza[0-9A-Za-z_-]{30,}', '[REDACTED]'),
        (r'(--token\s+)\S+', r'\1[REDACTED]'),
        (r'((?:password|secret|passwd)[=:]\s*)\S+', r'\1[REDACTED]'),
        (r'AKIA[0-9A-Z]{16}', '[REDACTED]'),
        (r'("(?:api_key|apikey|api_secret|token|secret|password|access_token|refresh_token|auth)"\s*:\s*)"[^"]*"', r'\1"[REDACTED]"'),
    ]
    for pat, repl in patterns:
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    return text

d = json.load(sys.stdin)
ti = d.get('tool_input', {})
skill = ti.get('skill', '')
if not skill:
    sys.exit(0)

raw_args = ti.get('args', '')
entry = {
    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'date': datetime.now().strftime('%Y-%m-%d'),
    'skill': skill,
    'args': scrub_credentials(raw_args),
    'args_len': len(raw_args),
    'session_id': os.environ.get('CLAUDE_SESSION_ID', 'unknown')
}
print(json.dumps(entry))
" 2>/dev/null)

if [[ -n "$ENTRY" ]]; then
  echo "$ENTRY" >> "$HOME/.claude/.claude/tracking/skill-telemetry.jsonl"
  rotate_log "$HOME/.claude/.claude/tracking/skill-telemetry.jsonl" 500 jsonl
  SKILL_NAME=$(echo "$ENTRY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('skill','unknown'))" 2>/dev/null)
  bash "$HOME/.claude/scripts/emit-event.sh" "hook.log-skill-invocation" "hook" "${SKILL_NAME:-unknown}" "{\"result\":\"logged\"}" || true
fi

exit 0
