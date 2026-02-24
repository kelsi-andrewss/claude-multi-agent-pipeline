#!/usr/bin/env bash
# diff-gate.sh — Post-coder diff gate (ORCHESTRATION.md §11)
# Usage: diff-gate.sh <repo-root> <epic-slug> <story-branch> <write-file1> [<write-file2> ...]
#
# Prints the final list of changed files to stdout.
# Exits 0 if diff matches write-targets exactly (after any restoration).
# Exits 1 if diff is empty (nothing was committed).
# Exits 2 if unexpected files remain after restoration (manual fix needed).
# Never edits source files — only restores files to epic branch state.
set -euo pipefail

REPO_ROOT="$1"
EPIC_SLUG="$2"
STORY_BRANCH="$3"
shift 3
WRITE_FILES=("$@")

EPIC_BRANCH="epic/${EPIC_SLUG}"
WORKTREE_DIR="${REPO_ROOT}/.claude/worktrees/${STORY_BRANCH}"

# ── 1. Fetch + rebase onto epic branch ───────────────────────────────────────
git -C "$WORKTREE_DIR" fetch origin
git -C "$WORKTREE_DIR" rebase "${EPIC_BRANCH}"

# ── 2. Get changed files ──────────────────────────────────────────────────────
DIFF_FILES=()
while IFS= read -r line; do DIFF_FILES+=("$line"); done < <(git -C "$WORKTREE_DIR" diff "${EPIC_BRANCH}..HEAD" --name-only)

if [ ${#DIFF_FILES[@]} -eq 0 ]; then
  echo "ERROR: diff is empty — no commits found on ${STORY_BRANCH} beyond ${EPIC_BRANCH}" >&2
  exit 1
fi

# ── 3. Find out-of-scope files ────────────────────────────────────────────────
declare -a EXTRA_FILES=()
for f in "${DIFF_FILES[@]}"; do
  found=0
  for wf in "${WRITE_FILES[@]}"; do
    if [ "$f" = "$wf" ]; then
      found=1
      break
    fi
  done
  if [ "$found" -eq 0 ]; then
    EXTRA_FILES+=("$f")
  fi
done

# ── 4. Restore out-of-scope files to epic branch state ───────────────────────
if [ ${#EXTRA_FILES[@]} -gt 0 ]; then
  echo "Restoring out-of-scope files: ${EXTRA_FILES[*]}"
  git -C "$WORKTREE_DIR" checkout "${EPIC_BRANCH}" -- "${EXTRA_FILES[@]}"
  git -C "$WORKTREE_DIR" commit -m "fix: restore out-of-scope files to epic branch state"

  # Re-check diff
  DIFF_FILES=()
  while IFS= read -r line; do DIFF_FILES+=("$line"); done < <(git -C "$WORKTREE_DIR" diff "${EPIC_BRANCH}..HEAD" --name-only)
fi

# ── 5. Verify diff matches write-targets exactly ──────────────────────────────
declare -a STILL_EXTRA=()
for f in "${DIFF_FILES[@]}"; do
  found=0
  for wf in "${WRITE_FILES[@]}"; do
    if [ "$f" = "$wf" ]; then
      found=1
      break
    fi
  done
  if [ "$found" -eq 0 ]; then
    STILL_EXTRA+=("$f")
  fi
done

if [ ${#STILL_EXTRA[@]} -gt 0 ]; then
  echo "ERROR: unexpected files still in diff after restoration: ${STILL_EXTRA[*]}" >&2
  exit 2
fi

echo "diff-gate OK: ${DIFF_FILES[*]}"
