#!/usr/bin/env bash
# merge-story.sh — Story merge sequence (ORCHESTRATION.md §12)
# Usage: merge-story.sh <repo-root> <epic-slug> <story-branch> <story-title> <pr-number|""> <epic-title>
#
# <pr-number> is the existing epic PR number, or empty string if this is the first story merging.
# When empty, creates the epic PR and prints "PR_NUMBER=<n>" to stdout for the caller to persist.
# Exits 0 on success. Never edits source files.
set -euo pipefail

REPO_ROOT="$1"
EPIC_SLUG="$2"
STORY_BRANCH="$3"   # e.g. story/my-feature
STORY_TITLE="$4"
PR_NUMBER="$5"      # existing epic PR number, or "" if first story
EPIC_TITLE="$6"

EPIC_BRANCH="epic/${EPIC_SLUG}"
WORKTREE_DIR="${REPO_ROOT}/.claude/worktrees/${STORY_BRANCH}"

# ── 1. Rebase story onto epic branch ─────────────────────────────────────────
git -C "$WORKTREE_DIR" fetch origin
git -C "$WORKTREE_DIR" rebase "origin/${EPIC_BRANCH}"

# ── 1b. Diff-stat guard ───────────────────────────────────────────────────────
CHANGED=$(git -C "$REPO_ROOT" diff --stat "origin/${EPIC_BRANCH}" "${STORY_BRANCH}" | tail -1)
if [ -z "$CHANGED" ]; then
  echo "ERROR: diff between ${STORY_BRANCH} and ${EPIC_BRANCH} is empty — story changes may have been lost. Aborting." >&2
  exit 3
fi
echo "Diff guard OK: ${CHANGED}"

# ── 2. Merge story into epic branch ──────────────────────────────────────────
git -C "$REPO_ROOT" checkout "${EPIC_BRANCH}"
git -C "$REPO_ROOT" merge --ff-only "${STORY_BRANCH}" || \
  git -C "$REPO_ROOT" merge --no-ff "${STORY_BRANCH}" -m "merge: ${STORY_BRANCH} into ${EPIC_BRANCH}"

git -C "$REPO_ROOT" push origin "${EPIC_BRANCH}"

# ── 3. Epic PR — create or update ────────────────────────────────────────────
if [ -z "$PR_NUMBER" ]; then
  EXISTING_PR=$(gh pr view "${EPIC_BRANCH}" --json number --jq '.number' 2>/dev/null || echo "")
  if [ -n "$EXISTING_PR" ]; then
    PR_NUMBER="$EXISTING_PR"
    echo "PR_NUMBER=${PR_NUMBER}"
  else
    PR_URL=$(gh pr create \
      --base main \
      --head "${EPIC_BRANCH}" \
      --title "${EPIC_TITLE}" \
      --body "## Stories merged"$'\n'"- ${STORY_TITLE}")
    NEW_PR_NUMBER=$(gh pr view "$PR_URL" --json number --jq '.number')
    echo "PR_NUMBER=${NEW_PR_NUMBER}"
    PR_NUMBER="$NEW_PR_NUMBER"
  fi
fi
CURRENT_BODY=$(gh pr view "$PR_NUMBER" --json body --jq '.body' 2>/dev/null || echo "## Stories merged")
gh pr edit "$PR_NUMBER" --body "${CURRENT_BODY}"$'\n'"- ${STORY_TITLE}" 2>/dev/null || true

# ── 4. Cleanup worktree and branch ────────────────────────────────────────────
git -C "$REPO_ROOT" worktree remove "${WORKTREE_DIR}" --force 2>/dev/null || true
git -C "$REPO_ROOT" worktree prune
git -C "$REPO_ROOT" branch -d "${STORY_BRANCH}" 2>/dev/null || {
  git -C "$REPO_ROOT" update-ref -d "refs/heads/${STORY_BRANCH}"
}
git -C "$REPO_ROOT" push origin --delete "${STORY_BRANCH}" 2>/dev/null || true

echo "merge-story OK: ${STORY_BRANCH} → ${EPIC_BRANCH}"
