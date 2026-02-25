#!/usr/bin/env bash
set -e

# merge-epic.sh
# Args: <project-root> <epic-slug> <pr-number>

PROJECT_ROOT="$1"
EPIC_SLUG="$2"
PR_NUMBER="$3"

if [ -z "$PROJECT_ROOT" ] || [ -z "$EPIC_SLUG" ] || [ -z "$PR_NUMBER" ]; then
  echo "Usage: merge-epic.sh <project-root> <epic-slug> <pr-number>" >&2
  exit 1
fi

EPIC_BRANCH="epic/${EPIC_SLUG}"

cd "$PROJECT_ROOT"

echo "Squash-merging epic PR #${PR_NUMBER} (${EPIC_BRANCH})"

# Squash-merge via gh — this also deletes the remote branch
gh pr merge --squash --delete-branch "$PR_NUMBER"

# Delete local epic branch ref
echo "Deleting local epic branch ${EPIC_BRANCH}"
if git show-ref --verify --quiet "refs/heads/${EPIC_BRANCH}"; then
  # Switch away from epic branch first if we're on it
  CURRENT=$(git rev-parse --abbrev-ref HEAD)
  if [ "$CURRENT" = "$EPIC_BRANCH" ]; then
    git checkout main 2>/dev/null || git checkout -
  fi

  # Use -d; if it fails because not fully merged from git's perspective, advance ref first
  if ! git branch -d "$EPIC_BRANCH" 2>/dev/null; then
    git update-ref "refs/heads/${EPIC_BRANCH}" "$(git rev-parse main)"
    git branch -d "$EPIC_BRANCH"
  fi
else
  echo "Local epic branch ${EPIC_BRANCH} does not exist — skipping local delete"
fi

echo "Epic ${EPIC_SLUG} merged and cleaned up"
exit 0
