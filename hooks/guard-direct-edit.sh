#!/bin/bash
# PreToolUse hook for Edit and Write.
# Allows edits only when the file being edited is inside a story worktree
# (.claude/worktrees/). Blocks direct edits to project source files from
# the main session.
#
# Enhanced: also checks the active story's write_targets list in epics.db.
# If the file is not in write_targets AND not in an allowed path, blocks with
# a scope-creep message. Falls back to warn-only if epics.db is unavailable.
#
# Coder agents running inside a worktree pass automatically because their
# file paths resolve under the worktree directory.

source "$(dirname "$0")/lib/profile.sh"
require_profile 3

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

# Allow edits in non-git directories — guard only applies to git-tracked projects
FILE_DIR=$(dirname "$FILE_PATH")
if [[ -n "$FILE_DIR" ]] && ! git -C "$FILE_DIR" rev-parse --git-dir &>/dev/null 2>&1; then
  exit 0
fi

# Allow edits to ~/.claude/ files — scoped when working IN the ~/.claude project
if [[ "$FILE_PATH" == "$HOME/.claude/"* ]]; then
  if [[ "$PWD" == "$HOME/.claude" || "$PWD" == "$HOME/.claude/"* ]]; then
    # Working IN ~/.claude as a project — only allow orchestration artifacts
    case "$FILE_PATH" in
      # Behavioral/logging files the main session writes
      "$HOME/.claude/outcomes.md"|\
      "$HOME/.claude/session-handoff.md"|\
      "$HOME/.claude/todos.md"|\
      "$HOME/.claude/skill-changelog.md")
        exit 0 ;;
      # Tracking files
      "$HOME/.claude/.claude/tracking/"*)
        exit 0 ;;
      # Memory files
      "$HOME/.claude/memory/"*|\
      "$HOME/.claude/projects/"*/memory/*)
        exit 0 ;;
      # Plan files (draft-plan writes these)
      "$HOME/.claude/plans/"*)
        exit 0 ;;
      # Settings (main session manages hook config)
      "$HOME/.claude/settings.json")
        exit 0 ;;
      # Everything else in ~/.claude/ is project code — block it
      *)
        ;; # fall through to blocking logic below
    esac
  else
    # Working in a DIFFERENT project — ~/.claude/ edits are config, allow them
    exit 0
  fi
fi

# Allow edits inside any story worktree
if [[ "$FILE_PATH" == */\.claude/worktrees/* ]]; then
  exit 0
fi

# Allow edits to the project's own .claude/ directory (settings, etc.)
if [[ "$FILE_PATH" == */\.claude/* ]]; then
  exit 0
fi

# Allow edits to temp files
if [[ "$FILE_PATH" == /tmp/* || "$FILE_PATH" == "$TMPDIR"* || "$FILE_PATH" == "$CLAUDE_TEMP_DIR"* ]]; then
  exit 0
fi

# Allow edits to plan files (orchestration artifacts written by draft-plan)
if [[ "$FILE_PATH" == */plans/*.md ]]; then
  exit 0
fi

# Allow edits during active /hotfix — sentinel contains allowed file path
# Fixed path (not PID-based) because the hook's PPID never matches the skill's $$
HOTFIX_SENTINEL="$CLAUDE_TEMP_DIR/hotfix-active"
if [[ -f "$HOTFIX_SENTINEL" ]]; then
  ALLOWED_FILE=$(cat "$HOTFIX_SENTINEL")
  if [[ "$FILE_PATH" == *"$ALLOWED_FILE"* || "$ALLOWED_FILE" == *"$FILE_PATH"* ]]; then
    exit 0
  fi
fi

# Enhanced check: look up the active story's write_targets in epics.db.
# If a running story exists, check whether this file is in scope.
DB_FILE="$HOME/.claude/.claude/epics.db"

if [[ -f "$DB_FILE" ]]; then
  RESULT=$(python3 -c "
import subprocess, sys

db_path = '$DB_FILE'
file_path = '$FILE_PATH'

running_states = \"('in-progress','in-review','approved','running','testing','reviewing','merging')\"

try:
    r = subprocess.run(
        ['sqlite3', db_path,
         f'SELECT write_targets FROM stories WHERE state IN {running_states} AND archived=0;'],
        capture_output=True, text=True, timeout=5
    )
    rows = [line.strip() for line in r.stdout.strip().splitlines() if line.strip()]
except Exception:
    print('EPICS_UNAVAILABLE')
    sys.exit(0)

if not rows:
    print('NO_RUNNING_STORY')
    sys.exit(0)

# write_targets is a newline or comma-separated list of file paths
all_write_files = []
for row in rows:
    for wf in row.replace(',', '\n').splitlines():
        wf = wf.strip()
        if wf:
            all_write_files.append(wf)

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
