#!/bin/bash
# Blocks Edit, Write, and Task tool calls until ORCHESTRATION.md has been
# explicitly Read this session. The marker is set by the PostToolUse hook
# on Read when the path matches ORCHESTRATION.md.

SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
MARKER="/tmp/orch-read-${SESSION_ID}"

if [ ! -f "$MARKER" ]; then
  echo "ORCHESTRATION.md has not been explicitly Read this session. Use the Read tool on /Users/kelsiandrews/.claude/ORCHESTRATION.md before making code changes." >&2
  exit 2
fi

exit 0
