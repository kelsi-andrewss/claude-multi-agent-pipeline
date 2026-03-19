#!/bin/bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: worktree-cleanup.sh --worktree-path <path> [--branch <name>] [--force]

Remove a git worktree and optionally delete its branch (local + remote).
Handles orphaned worktrees, locked states, and already-removed paths.

Arguments:
  --worktree-path  Absolute path to the worktree to remove (required)
  --branch         Branch name to delete after worktree removal (optional)
  --force          Force removal even if worktree has uncommitted changes
  --help           Show this help message
USAGE
  exit 2
}

WORKTREE_PATH=""
BRANCH=""
FORCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worktree-path) WORKTREE_PATH="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --force) FORCE="true"; shift ;;
    --help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$WORKTREE_PATH" ]]; then
  echo "Error: --worktree-path is required" >&2
  usage
fi

REMOVED_WORKTREE="false"
REMOVED_BRANCH="false"
WARNINGS=""

add_warning() {
  if [[ -n "$WARNINGS" ]]; then
    WARNINGS="$WARNINGS|||$1"
  else
    WARNINGS="$1"
  fi
}

emit_error() {
  python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': sys.argv[1],
    'removed_worktree': False,
    'removed_branch': False
}))
" "$1"
  exit 1
}

# Resolve the git repo root. When the worktree exists on disk, use git rev-parse.
# When it doesn't (stale), walk up from the worktree path looking for .git directory.
if [[ -d "$WORKTREE_PATH" ]]; then
  GIT_ROOT=$(git -C "$WORKTREE_PATH" rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$||' || true)
else
  GIT_ROOT=$(python3 -c "
import os, sys
p = os.path.dirname(os.path.realpath(sys.argv[1]))
while p != '/':
    if os.path.isdir(os.path.join(p, '.git')):
        print(p)
        break
    p = os.path.dirname(p)
" "$WORKTREE_PATH")
fi

if [[ -z "$GIT_ROOT" ]]; then
  emit_error "Cannot find git repo for worktree: $WORKTREE_PATH"
fi

# Check if worktree path exists on disk
if [[ ! -d "$WORKTREE_PATH" ]]; then
  # Check for stale entry in worktree list (resolve symlinks for comparison)
  WT_PORCELAIN=$(git -C "$GIT_ROOT" worktree list --porcelain 2>/dev/null || true)
  STALE=$(python3 -c "
import os, sys
target = os.path.realpath(sys.argv[1])
porcelain = sys.argv[2]
for line in porcelain.split('\n'):
    if line.startswith('worktree '):
        wt = line[len('worktree '):]
        if os.path.realpath(wt) == target:
            print('found')
            break
" "$WORKTREE_PATH" "$WT_PORCELAIN")
  if [[ "$STALE" == "found" ]]; then
    echo "Found stale worktree entry, pruning..." >&2
    git -C "$GIT_ROOT" worktree prune >&2
    REMOVED_WORKTREE="true"
  else
    emit_error "Worktree path does not exist: $WORKTREE_PATH"
  fi
else
  # Worktree exists on disk
  if [[ "$FORCE" != "true" ]]; then
    DIRTY=$(git -C "$WORKTREE_PATH" status --porcelain 2>/dev/null || true)
    if [[ -n "$DIRTY" ]]; then
      emit_error "Worktree has uncommitted changes. Use --force to remove anyway."
    fi
  fi

  # Remove worktree
  echo "Removing worktree at $WORKTREE_PATH..." >&2
  if [[ "$FORCE" == "true" ]]; then
    git -C "$GIT_ROOT" worktree remove --force "$WORKTREE_PATH" >&2 2>&1 || {
      echo "Force removal failed, trying harder..." >&2
      git -C "$GIT_ROOT" worktree remove --force "$WORKTREE_PATH" 2>/dev/null || true
    }
  else
    git -C "$GIT_ROOT" worktree remove "$WORKTREE_PATH" >&2 2>&1 || {
      echo "Normal removal failed, trying force..." >&2
      git -C "$GIT_ROOT" worktree remove --force "$WORKTREE_PATH" >&2 2>&1 || true
    }
  fi
  REMOVED_WORKTREE="true"

  # Prune
  git -C "$GIT_ROOT" worktree prune >&2
fi

# Handle branch deletion if requested
if [[ -n "$BRANCH" ]]; then
  # Delete local branch (redirect stdout to stderr to keep JSON stdout clean)
  if git -C "$GIT_ROOT" branch -D "$BRANCH" >&2 2>/dev/null; then
    echo "Deleted local branch $BRANCH" >&2
    REMOVED_BRANCH="true"
  else
    echo "Local branch $BRANCH not found or already deleted" >&2
    REMOVED_BRANCH="true"
  fi

  # Delete remote branch
  if ! git -C "$GIT_ROOT" push origin --delete "$BRANCH" 2>/dev/null; then
    add_warning "Failed to delete remote branch: origin/$BRANCH (may already be deleted)"
  fi
else
  REMOVED_BRANCH="false"
fi

# Emit result JSON
python3 -c "
import json, sys

warnings_raw = sys.argv[1]
removed_wt = sys.argv[2] == 'true'
removed_br = sys.argv[3] == 'true'

result = {
    'status': 'success',
    'removed_worktree': removed_wt,
    'removed_branch': removed_br
}

if warnings_raw:
    result['warnings'] = warnings_raw.split('|||')

print(json.dumps(result))
" "$WARNINGS" "$REMOVED_WORKTREE" "$REMOVED_BRANCH"
