#!/usr/bin/env bash
set -e

# setup-story.sh
# Args: <project-root> <epic-slug> <story-branch> <story-slug>

PROJECT_ROOT="$1"
EPIC_SLUG="$2"
STORY_BRANCH="$3"
STORY_SLUG="$4"

if [ -z "$PROJECT_ROOT" ] || [ -z "$EPIC_SLUG" ] || [ -z "$STORY_BRANCH" ] || [ -z "$STORY_SLUG" ]; then
  echo "Usage: setup-story.sh <project-root> <epic-slug> <story-branch> <story-slug>" >&2
  exit 1
fi

EPIC_BRANCH="epic/${EPIC_SLUG}"
WORKTREE_PATH="${PROJECT_ROOT}/.claude/worktrees/${STORY_BRANCH}"

cd "$PROJECT_ROOT"

# Create or check out epic branch
if git show-ref --verify --quiet "refs/heads/${EPIC_BRANCH}"; then
  echo "Epic branch ${EPIC_BRANCH} already exists"
  git checkout "$EPIC_BRANCH" 2>/dev/null || true
else
  echo "Creating epic branch ${EPIC_BRANCH} from main"
  git checkout -b "$EPIC_BRANCH" main
  git checkout - 2>/dev/null || true
fi

# Create story worktree
if [ -d "$WORKTREE_PATH" ]; then
  echo "Worktree ${WORKTREE_PATH} already exists"
else
  # Create story branch if it doesn't already exist
  if git show-ref --verify --quiet "refs/heads/${STORY_BRANCH}"; then
    echo "Story branch ${STORY_BRANCH} already exists — adding worktree"
    git worktree add "$WORKTREE_PATH" "$STORY_BRANCH"
  else
    echo "Creating story branch ${STORY_BRANCH} from ${EPIC_BRANCH}"
    git worktree add -b "$STORY_BRANCH" "$WORKTREE_PATH" "$EPIC_BRANCH"
  fi
fi

echo "Setup complete: worktree at ${WORKTREE_PATH}"
exit 0
