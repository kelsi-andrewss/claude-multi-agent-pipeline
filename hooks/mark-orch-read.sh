#!/bin/bash
# PostToolUse hook on Read. If the file read was ORCHESTRATION.md, set the
# session marker so the PreToolUse guard allows Edit/Write/Task calls.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

if [[ "$FILE_PATH" == *"ORCHESTRATION.md" ]]; then
  SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
  touch "/tmp/orch-read-${SESSION_ID}"
fi

exit 0
