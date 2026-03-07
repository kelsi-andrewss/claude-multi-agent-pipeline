#!/bin/bash
# PreToolUse hook for Read.
# Blocks reading .env files — secret values must never flow through the API.
# .env.example is allowed (contains placeholder names, not real values).

source "$(dirname "$0")/lib/profile.sh"
require_profile 2

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null)

BASENAME=$(basename "$FILE_PATH")

# Allow .env.example — it contains names, not secrets
if [[ "$BASENAME" == ".env.example" || "$BASENAME" == ".env.sample" || "$BASENAME" == ".env.template" ]]; then
  exit 0
fi

# Block .env* files
if [[ "$BASENAME" == .env* ]]; then
  echo "BLOCKED: Reading .env files is prohibited — secret values must not flow through the API." >&2
  echo "File attempted: $FILE_PATH" >&2
  echo "If you need to know what vars are set, ask the user to confirm." >&2
  exit 2
fi

exit 0
