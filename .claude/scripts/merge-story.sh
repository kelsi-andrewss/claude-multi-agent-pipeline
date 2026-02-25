#!/usr/bin/env bash
set -e

# merge-story.sh
# Args: <project-root> <epic-slug> <story-branch> <story-title> [<pr-number>]
# Outputs: MERGED:<story-branch>:PR_NUMBER=<n>

PROJECT_ROOT="$1"
EPIC_SLUG="$2"
STORY_BRANCH="$3"
STORY_TITLE="$4"
PR_NUMBER="${5:-}"

if [ -z "$PROJECT_ROOT" ] || [ -z "$EPIC_SLUG" ] || [ -z "$STORY_BRANCH" ] || [ -z "$STORY_TITLE" ]; then
  echo "Usage: merge-story.sh <project-root> <epic-slug> <story-branch> <story-title> [<pr-number>]" >&2
  exit 1
fi

EPIC_BRANCH="epic/${EPIC_SLUG}"
WORKTREE_PATH="${PROJECT_ROOT}/.claude/worktrees/${STORY_BRANCH}"

cd "$PROJECT_ROOT"

# Check out the epic branch in main worktree
git checkout "$EPIC_BRANCH"

# Merge story branch into epic branch (no fast-forward)
echo "Merging ${STORY_BRANCH} into ${EPIC_BRANCH}"
git merge --no-ff "$STORY_BRANCH" -m "merge: ${STORY_TITLE}"

# Create or update the epic PR
EPIC_BRANCH_REMOTE_EXISTS=$(git ls-remote --heads origin "$EPIC_BRANCH" 2>/dev/null | wc -l | tr -d ' ')

if [ "$EPIC_BRANCH_REMOTE_EXISTS" -eq 0 ]; then
  git push -u origin "$EPIC_BRANCH"
else
  git push origin "$EPIC_BRANCH"
fi

if [ -n "$PR_NUMBER" ]; then
  # Update existing PR
  echo "Updating epic PR #${PR_NUMBER}"
  gh pr edit "$PR_NUMBER" --title "${EPIC_SLUG}" 2>/dev/null || true
  FINAL_PR="$PR_NUMBER"
else
  # Check if PR already exists for this branch
  EXISTING_PR=$(gh pr list --head "$EPIC_BRANCH" --json number --jq '.[0].number' 2>/dev/null || true)
  if [ -n "$EXISTING_PR" ] && [ "$EXISTING_PR" != "null" ]; then
    echo "Epic PR already exists: #${EXISTING_PR}"
    FINAL_PR="$EXISTING_PR"
  else
    echo "Creating epic PR for ${EPIC_BRANCH}"
    FINAL_PR=$(gh pr create \
      --base main \
      --head "$EPIC_BRANCH" \
      --title "${EPIC_SLUG}" \
      --body "Epic branch: ${EPIC_SLUG}" \
      --json number \
      --jq '.number' 2>/dev/null)
    echo "Created epic PR #${FINAL_PR}"
  fi
fi

# Remove story worktree
echo "Removing story worktree at ${WORKTREE_PATH}"
git worktree remove --force "$WORKTREE_PATH" 2>/dev/null || true

# Delete story branch (use -d; advance ref first if needed)
echo "Deleting story branch ${STORY_BRANCH}"
if ! git branch -d "$STORY_BRANCH" 2>/dev/null; then
  # Advance ref to HEAD of epic branch so -d considers it merged
  git update-ref "refs/heads/${STORY_BRANCH}" "$EPIC_BRANCH"
  git branch -d "$STORY_BRANCH"
fi

echo "MERGED:${STORY_BRANCH}:PR_NUMBER=${FINAL_PR}"
exit 0
