#!/bin/bash
# Post-compaction hook: reinject critical context essentials
# Fires after context compaction to restore rules that get lost during summarization.
# Output goes to stdout and is injected as a system message.

ESSENTIALS_FILE="$HOME/.claude/.claude/context-essentials.md"

if [ -f "$ESSENTIALS_FILE" ]; then
  echo "=== POST-COMPACTION CONTEXT REINJECT ==="
  cat "$ESSENTIALS_FILE"
  echo "=== END REINJECT ==="
fi
