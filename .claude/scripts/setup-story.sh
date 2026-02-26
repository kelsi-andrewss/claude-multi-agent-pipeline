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

CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "HEAD")

# Sync local main to origin before branching
git fetch origin main > /dev/null 2>&1 || true
git update-ref refs/heads/main origin/main 2>/dev/null || true

# Sync epic branch from origin if it exists remotely
git fetch origin "${EPIC_BRANCH}" > /dev/null 2>&1 && \
  git update-ref "refs/heads/${EPIC_BRANCH}" "origin/${EPIC_BRANCH}" 2>/dev/null || true

# Create epic branch if it doesn't exist — use branch operation only, no checkout
if git show-ref --verify --quiet "refs/heads/${EPIC_BRANCH}"; then
  [ -n "$VERBOSE" ] && echo "Epic branch ${EPIC_BRANCH} already exists"
else
  [ -n "$VERBOSE" ] && echo "Creating epic branch ${EPIC_BRANCH} from main"
  git branch "$EPIC_BRANCH" main
fi

# Create story worktree — never checks out in main worktree
if [ -d "$WORKTREE_PATH" ]; then
  [ -n "$VERBOSE" ] && echo "Worktree ${WORKTREE_PATH} already exists"
else
  if git show-ref --verify --quiet "refs/heads/${STORY_BRANCH}"; then
    [ -n "$VERBOSE" ] && echo "Story branch ${STORY_BRANCH} already exists — adding worktree"
    git worktree add "$WORKTREE_PATH" "$STORY_BRANCH" > /dev/null 2>&1
  else
    [ -n "$VERBOSE" ] && echo "Creating story branch ${STORY_BRANCH} from ${EPIC_BRANCH}"
    git worktree add -b "$STORY_BRANCH" "$WORKTREE_PATH" "$EPIC_BRANCH" > /dev/null 2>&1
  fi
  trap 'git worktree remove --force "$WORKTREE_PATH" 2>/dev/null || true; git branch -D "$STORY_BRANCH" 2>/dev/null || true' ERR
fi

trap - ERR
[ -n "$VERBOSE" ] && echo "Main worktree remains on: ${CURRENT_BRANCH}"
echo "Setup complete: worktree at ${WORKTREE_PATH}"
exit 0
