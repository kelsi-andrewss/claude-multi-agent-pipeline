#!/bin/bash
# PreToolUse hook for EnterWorktree.
# Blocks the main session from entering worktrees.
echo "BLOCKED: The main session must not use EnterWorktree." >&2
echo "Story worktrees are created by background coder agents only." >&2
echo "See ORCHESTRATION.md §1." >&2
exit 2
