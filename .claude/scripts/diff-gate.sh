#!/usr/bin/env bash
set -e

# diff-gate.sh
# Args: <project-root> <epic-slug> <story-branch> <write-file1> [<write-file2> ...]
# Exit codes:
#   0 = diff matches write-targets; gate passes
#   1 = diff is empty (nothing committed)
#   2 = unexpected files remain after restoration

PROJECT_ROOT="$1"
EPIC_SLUG="$2"
STORY_BRANCH="$3"
shift 3

WRITE_FILES=("$@")

if [ -z "$PROJECT_ROOT" ] || [ -z "$EPIC_SLUG" ] || [ -z "$STORY_BRANCH" ] || [ ${#WRITE_FILES[@]} -eq 0 ]; then
  echo "Usage: diff-gate.sh <project-root> <epic-slug> <story-branch> <write-file1> [<write-file2> ...]" >&2
  exit 1
fi

EPIC_BRANCH="epic/${EPIC_SLUG}"
WORKTREE_PATH="${PROJECT_ROOT}/.claude/worktrees/${STORY_BRANCH}"

cd "$PROJECT_ROOT"

# Fetch latest
git fetch origin 2>/dev/null || git fetch 2>/dev/null || true

# Rebase story branch onto epic branch
echo "Rebasing ${STORY_BRANCH} onto ${EPIC_BRANCH}"
git -C "$WORKTREE_PATH" rebase "$EPIC_BRANCH"

# Get list of files changed in story vs epic branch
CHANGED_FILES=$(git -C "$WORKTREE_PATH" diff --name-only "${EPIC_BRANCH}...HEAD" 2>/dev/null || true)

if [ -z "$CHANGED_FILES" ]; then
  echo "Diff is empty — nothing committed in story branch" >&2
  exit 1
fi

echo "Changed files in story branch:"
echo "$CHANGED_FILES"

# Build a lookup set of allowed write-targets
declare -A ALLOWED
for f in "${WRITE_FILES[@]}"; do
  ALLOWED["$f"]=1
done

# Find files that are NOT in the write-targets list
RESTORED_ANY=0
OUT_OF_SCOPE=()

while IFS= read -r file; do
  if [ -z "${ALLOWED[$file]+_}" ]; then
    echo "Restoring out-of-scope file: ${file}"
    git -C "$WORKTREE_PATH" checkout "$EPIC_BRANCH" -- "$file" 2>/dev/null || true
    OUT_OF_SCOPE+=("$file")
    RESTORED_ANY=1
  fi
done <<< "$CHANGED_FILES"

# If any files were restored, commit the restoration
if [ "$RESTORED_ANY" -eq 1 ]; then
  echo "Committing restoration of out-of-scope files"
  git -C "$WORKTREE_PATH" add "${OUT_OF_SCOPE[@]}"
  git -C "$WORKTREE_PATH" commit -m "fix: restore out-of-scope files to epic branch state"
fi

# Verify no unexpected files remain
REMAINING=$(git -C "$WORKTREE_PATH" diff --name-only "${EPIC_BRANCH}...HEAD" 2>/dev/null || true)

UNEXPECTED=()
while IFS= read -r file; do
  if [ -z "${ALLOWED[$file]+_}" ]; then
    UNEXPECTED+=("$file")
  fi
done <<< "$REMAINING"

if [ ${#UNEXPECTED[@]} -gt 0 ]; then
  echo "Unexpected files remain after restoration:" >&2
  printf '  %s\n' "${UNEXPECTED[@]}" >&2
  exit 2
fi

echo "Diff gate passed"
exit 0
