#!/bin/bash
# Emit a structured event to the daily JSONL event log.
# Shell wrapper around hooks/lib/event_log.py for non-Python callers.
#
# Usage: scripts/emit-event.sh <event_type> <actor> <ref> [json_payload]
#
# Arguments:
#   $1 - Event type (required). Dot-notation string, e.g. "hook.fired"
#   $2 - Actor (required). Who triggered: "claude", "gemini", "user", "hook"
#   $3 - Ref (required). Context reference: story ID, skill name, file path
#   $4 - JSON payload (optional). Must be valid JSON object. Defaults to {}
#
# Output: JSON to stdout with path to the written file.
# Exit 0 on success, exit 1 on error.

set -euo pipefail

EVENT_TYPE="${1:-}"
ACTOR="${2:-}"
REF="${3:-}"
PAYLOAD="${4:-{}}"

if [[ -z "$EVENT_TYPE" || -z "$ACTOR" || -z "$REF" ]]; then
  echo "Usage: scripts/emit-event.sh <event_type> <actor> <ref> [json_payload]" >&2
  exit 1
fi

python3 - "$EVENT_TYPE" "$ACTOR" "$REF" "$PAYLOAD" <<'PYEOF'
import json, sys

sys.path.insert(0, __import__("os").path.expanduser("~/.claude"))
from hooks.lib.event_log import emit_event

event_type = sys.argv[1]
actor = sys.argv[2]
ref = sys.argv[3]
try:
    payload = json.loads(sys.argv[4])
except (json.JSONDecodeError, IndexError):
    payload = {}

path = emit_event(event_type, actor=actor, ref=ref, payload=payload)
if path is None:
    print('{"status":"error","path":null}')
    sys.exit(1)
print(json.dumps({"status": "ok", "path": path}))
PYEOF
