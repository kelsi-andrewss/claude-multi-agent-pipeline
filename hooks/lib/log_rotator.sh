#!/bin/bash
# Shared log rotation utility for JSONL and JSON array files.
# Source this file, then call:
#   rotate_log <filepath> <max_lines> <format>
#
# Arguments:
#   filepath   - absolute path to the log file
#   max_lines  - maximum number of entries to keep (e.g., 500)
#   format     - "jsonl" (one object per line) or "json_array" (top-level JSON array)
#
# Behavior:
#   - If file doesn't exist or is empty: no-op.
#   - If entry count <= max_lines: no-op.
#   - If entry count > max_lines: truncate to last max_lines entries, write atomically.
#   - Atomic write: write to .tmp, then mv (rename is atomic on same filesystem).
#   - Exit code 0 always (advisory - rotation failure must not break the hook).

rotate_log() {
  local filepath="$1"
  local max_lines="$2"
  local format="$3"

  [[ -f "$filepath" ]] || return 0
  [[ -s "$filepath" ]] || return 0

  if [[ "$format" == "jsonl" ]]; then
    local count
    count=$(wc -l < "$filepath")
    [[ "$count" -gt "$max_lines" ]] || return 0
    { tail -n "$max_lines" "$filepath" > "${filepath}.tmp" && mv "${filepath}.tmp" "$filepath"; } || true
  elif [[ "$format" == "json_array" ]]; then
    { python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
if len(d) <= int(sys.argv[2]):
    sys.exit(0)
with open(sys.argv[3], 'w') as f:
    json.dump(d[-int(sys.argv[2]):], f, indent=2)
" "$filepath" "$max_lines" "${filepath}.tmp" && mv "${filepath}.tmp" "$filepath"; } || true
  fi

  return 0
}
