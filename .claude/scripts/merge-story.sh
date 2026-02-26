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

CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "HEAD")

# Merge story into epic branch using the worktree — never touches main worktree checkout
echo "Merging ${STORY_BRANCH} into ${EPIC_BRANCH} via worktree"

# Get worktree for the epic branch, or do the merge via a temp worktree
EPIC_WORKTREE=$(git worktree list --porcelain | awk '/^worktree /{wt=$2} /^branch refs\/heads\/'${EPIC_BRANCH//\//\\/}'$/{print wt}')

if [ -n "$EPIC_WORKTREE" ]; then
  MERGE_DIR="$EPIC_WORKTREE"
  TEMP_EPIC_WORKTREE=""
else
  # Add a temp worktree for the epic branch
  TEMP_EPIC_WORKTREE="${PROJECT_ROOT}/.claude/worktrees/_epic-merge-${EPIC_SLUG}"
  git worktree add "$TEMP_EPIC_WORKTREE" "$EPIC_BRANCH"
  MERGE_DIR="$TEMP_EPIC_WORKTREE"
fi

git -C "$MERGE_DIR" merge --no-ff "$STORY_BRANCH" -m "merge: ${STORY_TITLE}"

# Push epic branch
EPIC_BRANCH_REMOTE_EXISTS=$(git ls-remote --heads origin "$EPIC_BRANCH" 2>/dev/null | wc -l | tr -d ' ')
if [ "$EPIC_BRANCH_REMOTE_EXISTS" -eq 0 ]; then
  git -C "$MERGE_DIR" push -u origin "$EPIC_BRANCH"
else
  git -C "$MERGE_DIR" push origin "$EPIC_BRANCH"
fi

# Clean up temp epic worktree if we created one
if [ -n "$TEMP_EPIC_WORKTREE" ]; then
  git worktree remove --force "$TEMP_EPIC_WORKTREE" 2>/dev/null || true
fi

if [ -n "$PR_NUMBER" ]; then
  echo "Updating epic PR #${PR_NUMBER}"
  gh pr edit "$PR_NUMBER" --title "${EPIC_SLUG}" 2>/dev/null || true
  FINAL_PR="$PR_NUMBER"
else
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
git worktree prune 2>/dev/null || true

# Delete story branch
echo "Deleting story branch ${STORY_BRANCH}"
git branch -D "$STORY_BRANCH" 2>/dev/null || true
git push origin --delete "$STORY_BRANCH" 2>/dev/null || true

echo "Main worktree remains on: ${CURRENT_BRANCH}"
echo "MERGED:${STORY_BRANCH}:PR_NUMBER=${FINAL_PR}"
exit 0
