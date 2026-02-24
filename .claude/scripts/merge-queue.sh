#!/usr/bin/env bash
# merge-queue.sh — Sequential diff-gate + merge for a list of stories (ORCHESTRATION.md §12)
#
# Usage: merge-queue.sh <repo-root> <manifest-json>
#
# <manifest-json> is a JSON array of story objects, each with:
#   {
#     "storyBranch":  "story/my-feature",
#     "storyTitle":   "My feature title",
#     "epicSlug":     "my-epic",
#     "epicTitle":    "My Epic Title",
#     "prNumber":     "86",           // "" if not yet created
#     "writeFiles":   ["src/foo.js"]  // files the coder was allowed to touch
#   }
#
# All stories in the list are processed in order. Each story:
#   1. Runs diff-gate.sh
#   2. Runs merge-story.sh
#   3. Prints "MERGED:<storyBranch>:PR_NUMBER=<n>" so the caller can update epics.json
#
# Exits 0 if all stories merged successfully.
# Exits non-zero on first failure, printing which story failed.
set -euo pipefail

REPO_ROOT="$1"
MANIFEST="$2"

SCRIPTS_DIR="${REPO_ROOT}/.claude/scripts"

# Parse story count
STORY_COUNT=$(echo "$MANIFEST" | python3 -c "import json,sys; data=json.load(sys.stdin); print(len(data))")

echo "merge-queue: processing ${STORY_COUNT} stories sequentially"

for i in $(seq 0 $((STORY_COUNT - 1))); do
  STORY_BRANCH=$(echo "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[$i]['storyBranch'])")
  STORY_TITLE=$(echo  "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[$i]['storyTitle'])")
  EPIC_SLUG=$(echo    "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[$i]['epicSlug'])")
  EPIC_TITLE=$(echo   "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[$i]['epicTitle'])")
  PR_NUMBER=$(echo    "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[$i].get('prNumber',''))")
  WRITE_FILES_JSON=$(echo "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(' '.join(d[$i]['writeFiles']))")

  echo ""
  echo "────────────────────────────────────────────────────────────"
  echo "Story $((i+1))/${STORY_COUNT}: ${STORY_BRANCH}"
  echo "────────────────────────────────────────────────────────────"

  # ── Step 1: diff-gate ───────────────────────────────────────────
  echo "Running diff-gate.sh..."
  # shellcheck disable=SC2086
  bash "${SCRIPTS_DIR}/diff-gate.sh" \
    "$REPO_ROOT" \
    "$EPIC_SLUG" \
    "$STORY_BRANCH" \
    $WRITE_FILES_JSON
  echo "diff-gate passed for ${STORY_BRANCH}"

  # ── Step 2: merge-story ─────────────────────────────────────────
  echo "Running merge-story.sh..."
  MERGE_OUTPUT=$(bash "${SCRIPTS_DIR}/merge-story.sh" \
    "$REPO_ROOT" \
    "$EPIC_SLUG" \
    "$STORY_BRANCH" \
    "$STORY_TITLE" \
    "$PR_NUMBER" \
    "$EPIC_TITLE")
  echo "$MERGE_OUTPUT"

  # Extract PR number for subsequent stories in same epic
  NEW_PR=$(echo "$MERGE_OUTPUT" | grep '^PR_NUMBER=' | cut -d= -f2 || true)
  if [ -n "$NEW_PR" ]; then
    PR_NUMBER="$NEW_PR"
    # Update PR_NUMBER in manifest for remaining stories with same epicSlug
    MANIFEST=$(echo "$MANIFEST" | python3 -c "
import json, sys
data = json.load(sys.stdin)
epic_slug = '${EPIC_SLUG}'
new_pr = '${NEW_PR}'
for entry in data:
    if entry.get('epicSlug') == epic_slug and not entry.get('prNumber'):
        entry['prNumber'] = new_pr
print(json.dumps(data))
")
  fi

  # Update PR body with generated description (stories, files changed, commits)
  if [ -n "$PR_NUMBER" ]; then
    EPIC_BRANCH="epic/${EPIC_SLUG}"
    PR_BODY=$(bash "${SCRIPTS_DIR}/generate-pr-body.sh" "$REPO_ROOT" "$EPIC_BRANCH" 2>/dev/null || echo "## Stories merged")
    # Use printf to safely handle multiline content and avoid shell interpolation
    gh pr edit "$PR_NUMBER" --body "$(printf '%s' "$PR_BODY")" 2>/dev/null || true
  fi

  echo "MERGED:${STORY_BRANCH}:PR_NUMBER=${PR_NUMBER}"
done

echo ""
echo "merge-queue: all ${STORY_COUNT} stories merged successfully"
