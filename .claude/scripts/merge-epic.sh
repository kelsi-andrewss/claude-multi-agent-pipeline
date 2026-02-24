#!/usr/bin/env bash
# merge-epic.sh — Epic merge sequence (ORCHESTRATION.md §13)
# Usage: merge-epic.sh <repo-root> <epic-slug> <pr-number>
#
# Squash-merges the epic branch into main via the existing PR, then deletes it.
# Exits 0 on success. Never edits source files.
set -euo pipefail

REPO_ROOT="$1"
EPIC_SLUG="$2"
PR_NUMBER="$3"

EPIC_BRANCH="epic/${EPIC_SLUG}"

# ── 1. Rebase epic onto latest main ──────────────────────────────────────────
git -C "$REPO_ROOT" fetch origin main
git -C "$REPO_ROOT" checkout "${EPIC_BRANCH}"
git -C "$REPO_ROOT" rebase origin/main
git -C "$REPO_ROOT" push origin "${EPIC_BRANCH}" --force-with-lease

# ── 1b. Diff-stat guard ───────────────────────────────────────────────────────
CHANGED=$(git -C "$REPO_ROOT" diff --stat origin/main "${EPIC_BRANCH}" | tail -1)
if [ -z "$CHANGED" ]; then
  echo "ERROR: diff between ${EPIC_BRANCH} and main is empty — all changes may have been lost. Aborting." >&2
  exit 3
fi
echo "Diff guard OK: ${CHANGED}"

# ── 2. Squash-merge PR into main and delete remote epic branch ───────────────
gh pr merge "$PR_NUMBER" --squash --delete-branch

# ── 3. Advance local main ref and delete local epic branch ───────────────────
git -C "$REPO_ROOT" fetch origin main --prune
git -C "$REPO_ROOT" update-ref refs/heads/main origin/main
git -C "$REPO_ROOT" branch -d "${EPIC_BRANCH}" 2>/dev/null || \
  git -C "$REPO_ROOT" update-ref -d "refs/heads/${EPIC_BRANCH}" && \
  git -C "$REPO_ROOT" branch -d "${EPIC_BRANCH}" 2>/dev/null || true

echo "merge-epic OK: ${EPIC_BRANCH} → main (PR #${PR_NUMBER}), branch deleted"
