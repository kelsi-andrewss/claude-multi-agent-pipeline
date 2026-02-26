#!/bin/bash
# PreToolUse hook for Edit and Write.
# Allows edits only when the file being edited is inside a story worktree
# (.claude/worktrees/). Blocks direct edits to project source files from
# the main session.
#
# Enhanced: also checks the active story's writeFiles list in epics.json.
# If the file is not in writeFiles AND not in an allowed path, blocks with
# a scope-creep message. Falls back to warn-only if epics.json is unavailable.
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

# Allow edits during active /hotfix — sentinel contains allowed file path
# Fixed path (not PID-based) because the hook's PPID never matches the skill's $$
HOTFIX_SENTINEL="/tmp/hotfix-active"
if [[ -f "$HOTFIX_SENTINEL" ]]; then
  ALLOWED_FILE=$(cat "$HOTFIX_SENTINEL")
  if [[ "$FILE_PATH" == *"$ALLOWED_FILE"* || "$ALLOWED_FILE" == *"$FILE_PATH"* ]]; then
    exit 0
  fi
fi

# Enhanced check: look up the active story's writeFiles in epics.json.
# If a running story exists, check whether this file is in scope.
EPICS_JSON=$(find /Users/kelsiandrews -maxdepth 5 -name "epics.json" -path "*/.claude/epics.json" 2>/dev/null | head -1)

if [[ -n "$EPICS_JSON" && -f "$EPICS_JSON" ]]; then
  RESULT=$(python3 -c "
import sys, json

epics_path = '$EPICS_JSON'
file_path = '$FILE_PATH'

try:
    with open(epics_path) as f:
        data = json.load(f)
except:
    print('EPICS_UNAVAILABLE')
    sys.exit(0)

stories = data.get('stories', [])
running_stories = [s for s in stories if s.get('state') in ('in-progress', 'in-review', 'approved', 'running', 'testing', 'reviewing', 'merging')]

if not running_stories:
    # No story running — use legacy block behavior
    print('NO_RUNNING_STORY')
    sys.exit(0)

# Check if file is in any running story's writeFiles
all_write_files = []
for s in running_stories:
    all_write_files.extend(s.get('writeFiles', []))

# Normalize: check if file_path ends with any write file path component
for wf in all_write_files:
    if file_path.endswith(wf) or wf in file_path:
        print('IN_WRITE_FILES')
        sys.exit(0)

print('OUT_OF_SCOPE')
" 2>/dev/null)

  case "$RESULT" in
    "IN_WRITE_FILES")
      # File is in an active story's writeFiles — but still block main session direct edits
      # (coders run in worktrees, not main session; this is a belt-and-suspenders check)
      echo "BLOCKED: Direct edits to project source files are not allowed from the main session." >&2
      echo "This file is in the story's writeFiles, but edits must go through the coder in the worktree." >&2
      echo "File attempted: $FILE_PATH" >&2
      exit 2
      ;;
    "OUT_OF_SCOPE")
      echo "BLOCKED: $FILE_PATH is not in any running story's writeFiles." >&2
      echo "Add it to the plan or edit in the correct worktree." >&2
      echo "File attempted: $FILE_PATH" >&2
      exit 2
      ;;
    "NO_RUNNING_STORY"|"EPICS_UNAVAILABLE"|"")
      # Fallback: use original block-all behavior
      echo "BLOCKED: Direct edits to project source files are not allowed from the main session." >&2
      echo "Use /todo \"description\" to route the change through the pipeline." >&2
      echo "File attempted: $FILE_PATH" >&2
      exit 2
      ;;
  esac
fi

# Block everything else — this is a direct edit to a project source file
echo "BLOCKED: Direct edits to project source files are not allowed from the main session." >&2
echo "Use /todo \"description\" to route the change through the pipeline." >&2
echo "File attempted: $FILE_PATH" >&2
exit 2
