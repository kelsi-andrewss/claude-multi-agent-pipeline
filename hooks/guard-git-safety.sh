#!/bin/bash
# PreToolUse hook for Bash.
# Hard-blocks dangerous git operations from the main session:
#   - git push origin main (only dev merges to main)
#   - git push --force (destructive)
#   - git commit on main or dev branch (all work on named branches)
#   - git reset --hard (destructive)
#   - git checkout . / git restore . (discards uncommitted work)
#   - git clean -f (deletes untracked files)
#
# Coder agents in worktrees are not affected — they work on story branches.

source "$(dirname "$0")/lib/profile.sh"
require_profile 2

INPUT=$(cat)

COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('command', ''))
" 2>/dev/null)

[ -z "$COMMAND" ] && exit 0

# Block force push
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force|git\s+push\s+-f\b'; then
  echo "BLOCKED: Force push is destructive and not allowed. Use normal push." >&2
  exit 2
fi

# Block push to main
if echo "$COMMAND" | grep -qE 'git\s+push\s+\S+\s+main\b'; then
  echo "BLOCKED: Cannot push directly to main. Only dev merges to main via /merge-worktree." >&2
  exit 2
fi

# Block reset --hard
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard'; then
  echo "BLOCKED: git reset --hard is destructive. Use git stash or git checkout <file> instead." >&2
  exit 2
fi

# Block git clean -f
if echo "$COMMAND" | grep -qE 'git\s+clean\s+-[a-zA-Z]*f'; then
  echo "BLOCKED: git clean -f deletes untracked files permanently. Review files first." >&2
  exit 2
fi

# Block wholesale discard of changes
if echo "$COMMAND" | grep -qE 'git\s+checkout\s+\.\s*$|git\s+restore\s+\.\s*$'; then
  echo "BLOCKED: Discarding all uncommitted changes. Use git stash or restore specific files." >&2
  exit 2
fi

# Block commits directly on main or dev (not in a worktree)
if echo "$COMMAND" | grep -qE 'git\s+commit'; then
  # Only block if we're on main or dev in the main worktree (not a story worktree)
  if [[ "$PWD" != */\.claude/worktrees/* && "$PWD" != /tmp/merge-dev-* ]]; then
    CURRENT_BRANCH=$(git branch --show-current 2>/dev/null)
    if [[ "$CURRENT_BRANCH" == "main" || "$CURRENT_BRANCH" == "dev" ]]; then
      echo "BLOCKED: Cannot commit directly to $CURRENT_BRANCH. Create a feature branch first." >&2
      echo "All work must happen on named branches (hotfix/<slug>, quickfix/<slug>, or story branch)." >&2
      exit 2
    fi
  fi
fi

exit 0
