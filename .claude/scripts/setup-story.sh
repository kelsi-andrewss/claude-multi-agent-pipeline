#!/usr/bin/env bash
# setup-story.sh — Run trigger git ops (ORCHESTRATION.md §9)
# Usage: setup-story.sh <repo-root> <epic-slug> <story-branch> <story-slug>
#
# Exits 0 on success. Exits non-zero and prints a message on any failure.
# Never edits source files.
set -euo pipefail

REPO_ROOT="$1"
EPIC_SLUG="$2"
STORY_BRANCH="$3"   # e.g. story/my-feature
STORY_SLUG="$4"     # e.g. my-feature  (used for worktree dir name)

EPIC_BRANCH="epic/${EPIC_SLUG}"
WORKTREE_DIR="${REPO_ROOT}/.claude/worktrees/${STORY_BRANCH}"

# ── 1. Epic branch ───────────────────────────────────────────────────────────
if git -C "$REPO_ROOT" show-ref --quiet "refs/heads/${EPIC_BRANCH}"; then
  # Branch exists locally — fetch, rebase only if epic has diverged from main
  git -C "$REPO_ROOT" fetch origin main
  git -C "$REPO_ROOT" checkout "${EPIC_BRANCH}"
  if git -C "$REPO_ROOT" merge-base --is-ancestor origin/main "${EPIC_BRANCH}"; then
    echo "Epic branch already contains origin/main — skipping rebase"
  else
    git -C "$REPO_ROOT" rebase origin/main
  fi
  git -C "$REPO_ROOT" push origin "${EPIC_BRANCH}"
else
  # Branch does not exist — create from origin/main and push
  git -C "$REPO_ROOT" fetch origin main
  git -C "$REPO_ROOT" checkout -b "${EPIC_BRANCH}" origin/main
  git -C "$REPO_ROOT" push -u origin "${EPIC_BRANCH}"
fi

# ── 2. Story worktree ─────────────────────────────────────────────────────────
if git -C "$REPO_ROOT" worktree list --porcelain | grep -q "worktree ${WORKTREE_DIR}$"; then
  echo "Worktree already exists at ${WORKTREE_DIR} — skipping creation"
else
  # Delete local story branch if it already exists (stale from a previous run)
  if git -C "$REPO_ROOT" show-ref --quiet "refs/heads/${STORY_BRANCH}"; then
    git -C "$REPO_ROOT" branch -d "${STORY_BRANCH}" 2>/dev/null || \
      git -C "$REPO_ROOT" update-ref -d "refs/heads/${STORY_BRANCH}"
  fi

  git -C "$REPO_ROOT" worktree add \
    "${WORKTREE_DIR}" \
    -b "${STORY_BRANCH}" \
    "${EPIC_BRANCH}"
fi

echo "setup-story OK: worktree=${WORKTREE_DIR} branch=${STORY_BRANCH} epic=${EPIC_BRANCH}"
