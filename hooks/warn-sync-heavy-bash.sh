#!/bin/bash
# PreToolUse hook for Bash.
# Warns (does not block) when a heavy command (build, test, git push/rebase/merge,
# npm install) is run synchronously (run_in_background not true) from the main session.
#
# Intent: surface discipline violations at the point of failure so Claude stops
# defaulting to sequential patterns when parallel execution is possible.
#
# Exit 0  = allow (with optional warning printed to stderr)
# Exit 2  = hard block (not used here — this hook only warns)

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

# If already running in background, no issue
if [[ "$RUN_IN_BG" == "true" ]]; then
  exit 0
fi

# Check if this is a heavy command that should typically be backgrounded.
# Patterns: npm run build, npm run test, npx vitest, git push, git rebase,
# git merge, git fetch (when followed by rebase), npm install, vite build.
HEAVY=0
if echo "$COMMAND" | grep -qE 'npm run (build|test|lint)|npx vitest|vite build'; then
  HEAVY=1
  REASON="build/test command"
fi
if echo "$COMMAND" | grep -qE 'git (push|rebase|fetch|merge)'; then
  HEAVY=1
  REASON="git network/rebase operation"
fi
if echo "$COMMAND" | grep -qE 'npm (install|ci)\b'; then
  HEAVY=1
  REASON="npm install"
fi

if [[ "$HEAVY" == "1" ]]; then
  echo "⚠ PARALLELISM WARNING: '$REASON' is running synchronously." >&2
  echo "  If there is other independent work (file reads, worktree setup, epics.json updates)," >&2
  echo "  add run_in_background: true and proceed immediately." >&2
  echo "  Only block on this result when the next action actually depends on it." >&2
fi

# Always allow — this is advisory only
exit 0
