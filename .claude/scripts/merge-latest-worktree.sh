#!/usr/bin/env bash
set -e

# merge-latest-worktree.sh
# Finds the most recently modified story worktree, runs diff-gate, then merge-story.
# Args: <project-root> (default: parent of scripts dir)

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${1:-$PWD}"
WORKTREES_DIR="${PROJECT_ROOT}/.claude/worktrees"
EPICS_DB="${PROJECT_ROOT}/.claude/epics.db"

if [ ! -d "$WORKTREES_DIR" ]; then
  echo "No worktrees directory found at ${WORKTREES_DIR}" >&2
  exit 1
fi

# Find most recently modified worktree directory
WORKTREE_PATH=$(ls -dt "${WORKTREES_DIR}"/story/* 2>/dev/null | head -1)

if [ -z "$WORKTREE_PATH" ]; then
  echo "No story worktrees found under ${WORKTREES_DIR}" >&2
  exit 1
fi

# Derive story branch from worktree path: worktrees/story/my-slug -> story/my-slug
STORY_BRANCH="story/$(basename "$WORKTREE_PATH")"

echo "Found worktree: ${WORKTREE_PATH}"
echo "Story branch:   ${STORY_BRANCH}"

# Look up story in epics.db via epics-cli.sh
STORY_JSON=$(bash "${SCRIPTS_DIR}/epics-cli.sh" "$EPICS_DB" story-by-branch "$STORY_BRANCH")

if [ -z "$STORY_JSON" ] || [ "$STORY_JSON" = "[]" ]; then
  echo "Story with branch ${STORY_BRANCH} not found in epics.db" >&2
  exit 1
fi

# Parse the JSON result (sqlite3 -json returns an array)
EPIC_SLUG=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); r=d[0] if isinstance(d,list) else d; print(r.get('epicId','').replace('epic-',''))" "$STORY_JSON")
STORY_TITLE=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); r=d[0] if isinstance(d,list) else d; print(r.get('title',''))" "$STORY_JSON")
PR_NUMBER=""
readarray -t WRITE_FILES < <(python3 -c "
import json,sys
d=json.loads(sys.argv[1])
r=d[0] if isinstance(d,list) else d
wf=r.get('writeFiles','[]')
if isinstance(wf,str): wf=json.loads(wf)
for f in wf: print(f)
" "$STORY_JSON")

echo "Epic slug:      ${EPIC_SLUG}"
echo "Story title:    ${STORY_TITLE}"
echo "Write files:    ${WRITE_FILES[*]}"
echo ""

# Run diff gate
echo "=== Running diff gate ==="
bash "${SCRIPTS_DIR}/diff-gate.sh" \
  "$PROJECT_ROOT" \
  "$EPIC_SLUG" \
  "$STORY_BRANCH" \
  "${WRITE_FILES[@]}"

echo ""

# Run merge
echo "=== Merging story ==="
bash "${SCRIPTS_DIR}/merge-story.sh" \
  "$PROJECT_ROOT" \
  "$EPIC_SLUG" \
  "$STORY_BRANCH" \
  "$STORY_TITLE" \
  "$PR_NUMBER"
