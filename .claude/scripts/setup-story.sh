#!/usr/bin/env bash
set -euo pipefail

# setup-story.sh — create a git worktree for a story branch
#
# Args:
#   <project-root>   absolute path to the .claude directory (the repo root)
#   <epic-slug>      slug of the parent epic (used for the epic branch name)
#   <story-branch>   full branch name, e.g. story/ghost-placement
#   <story-slug>     slug used to locate the story in epics.json

PROJECT_ROOT="${1:?project-root required}"
EPIC_SLUG="${2:?epic-slug required}"
STORY_BRANCH="${3:?story-branch required}"
STORY_SLUG="${4:?story-slug required}"

EPICS_JSON="${PROJECT_ROOT}/.claude/epics.json"
WORKTREES_BASE="${PROJECT_ROOT}/.claude/worktrees"
WORKTREE_PATH="${WORKTREES_BASE}/story/${STORY_SLUG}"

# Derive the epic branch name from the epic slug
EPIC_BRANCH="epic/${EPIC_SLUG}"

# Ensure the epic branch exists; create from main if not
if ! git -C "${PROJECT_ROOT}" show-ref --quiet "refs/heads/${EPIC_BRANCH}"; then
  git -C "${PROJECT_ROOT}" branch "${EPIC_BRANCH}" main
fi

# Create the story branch from the epic branch if it does not exist
if ! git -C "${PROJECT_ROOT}" show-ref --quiet "refs/heads/${STORY_BRANCH}"; then
  git -C "${PROJECT_ROOT}" branch "${STORY_BRANCH}" "${EPIC_BRANCH}"
fi

# Remove a stale worktree at the target path if present
if [ -d "${WORKTREE_PATH}" ]; then
  git -C "${PROJECT_ROOT}" worktree remove --force "${WORKTREE_PATH}" 2>/dev/null || true
fi

mkdir -p "${WORKTREES_BASE}/story"

# Look up the story entry in epics.json by matching the branch field
STORY_JSON=$(node -e "
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('${EPICS_JSON}', 'utf8'));
let found = null;
for (const epic of data.epics) {
  for (const story of (epic.stories || [])) {
    if (story.branch === '${STORY_BRANCH}') { found = story; break; }
  }
  if (found) break;
}
if (!found) { process.stderr.write('Story not found for branch ${STORY_BRANCH}\n'); process.exit(1); }
process.stdout.write(JSON.stringify(found));
")

SPARSE_OK=$(node -e "
const s = ${STORY_JSON};
process.stdout.write(String(s.sparseOk === true));
")

AGENT=$(node -e "
const s = ${STORY_JSON};
process.stdout.write(s.agent || '');
")

if [ "${SPARSE_OK}" = "true" ] && [ "${AGENT}" = "quick-fixer" ]; then
  # Collect files to include in the sparse checkout (writeFiles + readFiles)
  SPARSE_FILES=$(node -e "
const s = ${STORY_JSON};
const files = [...(s.writeFiles || []), ...(s.readFiles || [])];
process.stdout.write(files.join(' '));
")

  git -C "${PROJECT_ROOT}" worktree add --no-checkout "${WORKTREE_PATH}" "${STORY_BRANCH}"
  git -C "${WORKTREE_PATH}" sparse-checkout init --cone
  # shellcheck disable=SC2086
  git -C "${WORKTREE_PATH}" sparse-checkout set ${SPARSE_FILES}
  git -C "${WORKTREE_PATH}" checkout "${STORY_BRANCH}"

  echo "Sparse-checkout worktree created at ${WORKTREE_PATH} (files: ${SPARSE_FILES})"
else
  # Full checkout — architect stories and stories without sparseOk always take this path
  git -C "${PROJECT_ROOT}" worktree add "${WORKTREE_PATH}" "${STORY_BRANCH}"

  echo "Full-checkout worktree created at ${WORKTREE_PATH}"
fi
