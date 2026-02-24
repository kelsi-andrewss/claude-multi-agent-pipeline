#!/bin/bash
# PreToolUse hook for Bash.
# Warns (does not block) when:
#   1. A heavy command (build, test, git push/rebase/merge, npm install) runs
#      synchronously when it could be backgrounded.
#   2. A file-operation command (find, grep, cat, head, tail) is used when
#      dedicated tools (Glob, Grep, Read) should be used instead.
#
# Includes the exact corrected call with run_in_background: true suggestion.
#
# Exit 0 always (advisory only).
# Hook is async: true — never blocks the Bash call.

INPUT=$(cat)

# Extract run_in_background and command from tool input JSON
RUN_IN_BG=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inp = d.get('tool_input', {})
print(str(inp.get('run_in_background', False)).lower())
" 2>/dev/null)

COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('command', ''))
" 2>/dev/null)

# --- Check 1: heavy commands that should be backgrounded ---

if [[ "$RUN_IN_BG" != "true" ]]; then
  HEAVY=0
  REASON=""
  CMD_TYPE=""

  if echo "$COMMAND" | grep -qE 'npm run (build|test|lint)\b'; then
    HEAVY=1
    REASON="build/test/lint command"
    CMD_TYPE="npm"
  elif echo "$COMMAND" | grep -qE 'npx vitest|vite build'; then
    HEAVY=1
    REASON="build/test command"
    CMD_TYPE="npm"
  elif echo "$COMMAND" | grep -qE 'git (push|rebase|fetch|merge)\b'; then
    HEAVY=1
    REASON="git network/rebase operation"
    CMD_TYPE="git"
  elif echo "$COMMAND" | grep -qE 'npm (install|ci)\b'; then
    HEAVY=1
    REASON="npm install"
    CMD_TYPE="npm"
  fi

  if [[ "$HEAVY" == "1" ]]; then
    echo "" >&2
    echo "PARALLELISM WARNING: '$REASON' is running synchronously." >&2
    echo "  If there is independent work (file reads, worktree setup, epics.json updates)," >&2
    echo "  use run_in_background: true and proceed immediately." >&2
    echo "  Corrected call example:" >&2
    echo "    Bash(command: \"${COMMAND}\", run_in_background: true)" >&2
    echo "  Only block on this result when the next action actually depends on it." >&2
  fi
fi

# --- Check 2: file-operation commands that have dedicated tools ---

FILE_OP_TOOL=""
FILE_OP_REASON=""

# Check for find — suggest Glob
if echo "$COMMAND" | grep -qE '^find\b|[|;&&] find\b'; then
  FILE_OP_TOOL="Glob"
  FILE_OP_REASON="find"
fi

# Check for grep/rg — suggest Grep
if echo "$COMMAND" | grep -qE '^grep\b|^rg\b|[|;&&] grep\b|[|;&&] rg\b'; then
  FILE_OP_TOOL="Grep"
  FILE_OP_REASON="grep/rg"
fi

# Check for cat/head/tail reading files — suggest Read
if echo "$COMMAND" | grep -qE '^(cat|head|tail)\s+[^|]'; then
  FILE_OP_TOOL="Read"
  FILE_OP_REASON="cat/head/tail"
fi

# Check for sed/awk editing files — suggest Edit
if echo "$COMMAND" | grep -qE '^(sed|awk)\s'; then
  FILE_OP_TOOL="Edit"
  FILE_OP_REASON="sed/awk"
fi

if [[ -n "$FILE_OP_TOOL" ]]; then
  echo "" >&2
  echo "TOOL SUGGESTION: '$FILE_OP_REASON' detected — prefer the dedicated $FILE_OP_TOOL tool instead." >&2
  echo "  Dedicated tools have correct permissions, better output formatting, and avoid shell quoting issues." >&2
fi

# Always allow — this is advisory only
exit 0
