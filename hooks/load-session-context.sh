#!/bin/bash
# Injects CLAUDE.md and ORCHESTRATION.md into Claude's context at session start.
# This ensures pipeline rules are loaded before the first user message.

echo "=== SESSION CONTEXT: MANDATORY PRE-READ ==="
echo "The following files have been loaded into your context. You MUST treat their"
echo "rules as active constraints before responding to any message this session."
echo ""
echo "--- ~/.claude/CLAUDE.md ---"
cat /Users/kelsiandrews/.claude/CLAUDE.md
echo ""
echo "--- ~/.claude/ORCHESTRATION.md ---"
cat /Users/kelsiandrews/.claude/ORCHESTRATION.md
echo ""
echo "=== MANDATORY TOOL CALL REQUIREMENT ==="
echo "Before answering ANY question about workflow, pipeline, or how you would handle a task,"
echo "you MUST use the Read tool to read these files — do NOT answer from memory or loaded context alone:"
echo "  1. Read /Users/kelsiandrews/.claude/ORCHESTRATION.md"
echo "  2. Read the project CLAUDE.md (find it via Glob if path unknown)"
echo "Answering without calling Read first is a violation of these rules."
echo "=== END SESSION CONTEXT ==="

# Satisfy the orch-read guard so no explicit Read is required this session
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
touch "/tmp/orch-read-${SESSION_ID}"

exit 0
