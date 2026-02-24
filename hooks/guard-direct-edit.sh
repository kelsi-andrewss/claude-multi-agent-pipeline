#!/bin/bash
# PreToolUse hook for Edit and Write.
# Allows edits only when the file being edited is inside a story worktree
# (.claude/worktrees/). Blocks all direct edits to project source files
# from the main session.
#
# Coder agents running inside a worktree pass automatically because their
# file paths resolve under the worktree directory.

# Fast path: if the session CWD is inside a story worktree, allow all edits immediately.
# This avoids the python3 JSON parse on every Edit call inside coder agents.
if [[ "$PWD" == */\.claude/worktrees/* ]]; then
  cat > /dev/null
  exit 0
fi

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
path = d.get('tool_input', {}).get('file_path', '')
if not path:
    path = d.get('tool_input', {}).get('path', '')
print(path)
" 2>/dev/null)

# Allow edits to ~/.claude/ config files (skills, hooks, settings, CLAUDE.md at user level)
if [[ "$FILE_PATH" == /Users/kelsiandrews/.claude/* ]]; then
  exit 0
fi

# Allow edits inside any story worktree
if [[ "$FILE_PATH" == */\.claude/worktrees/* ]]; then
  exit 0
fi

# Allow edits to the project's own .claude/ directory (epics.json, settings, etc.)
if [[ "$FILE_PATH" == */\.claude/* ]]; then
  exit 0
fi

# Allow edits to temp/plan files
if [[ "$FILE_PATH" == /tmp/* || "$FILE_PATH" == "$TMPDIR"* ]]; then
  exit 0
fi

# Block everything else — this is a direct edit to a project source file
echo "BLOCKED: Direct edits to project source files are not allowed from the main session." >&2
echo "Use /todo \"description\" to route the change through the pipeline." >&2
echo "File attempted: $FILE_PATH" >&2
exit 2
