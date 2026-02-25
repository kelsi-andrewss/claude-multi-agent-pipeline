#!/usr/bin/env bash
set -e

PROJECT_ROOT="$1"
MANIFEST="$2"

if [ -z "$PROJECT_ROOT" ] || [ -z "$MANIFEST" ]; then
  echo "Usage: merge-queue.sh <project-root> '<json-manifest>'" >&2
  exit 1
fi

SCRIPTS_DIR="$(dirname "$0")"

STORY_COUNT=$(echo "$MANIFEST" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

for i in $(seq 0 $((STORY_COUNT - 1))); do
  STORY_BRANCH=$(echo "$MANIFEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i]['storyBranch'])")
  STORY_TITLE=$(echo "$MANIFEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i]['storyTitle'])")
  EPIC_SLUG=$(echo "$MANIFEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i]['epicSlug'])")
  EPIC_TITLE=$(echo "$MANIFEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i]['epicTitle'])")
  PR_NUMBER=$(echo "$MANIFEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$i].get('prNumber',''))")
  WRITE_FILES=$(echo "$MANIFEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(d[$i].get('writeFiles',[])))")

  EPIC_BRANCH="epic/${EPIC_SLUG}"

  echo "--- Processing: ${STORY_TITLE} (${STORY_BRANCH}) ---"

  bash "${SCRIPTS_DIR}/diff-gate.sh" "$PROJECT_ROOT" "$EPIC_SLUG" "$STORY_BRANCH" $WRITE_FILES || {
    DIFF_EXIT=$?
    echo "diff-gate failed for ${STORY_BRANCH} with exit code ${DIFF_EXIT}" >&2
    exit "$DIFF_EXIT"
  }

  git -C "$PROJECT_ROOT" checkout "$EPIC_BRANCH"
  git -C "$PROJECT_ROOT" merge --no-ff "$STORY_BRANCH" -m "merge: ${STORY_TITLE}"

  if [ -z "$PR_NUMBER" ]; then
    PR_BODY=$("${SCRIPTS_DIR}/generate-pr-body.sh" "$PROJECT_ROOT" "$EPIC_SLUG" "$EPIC_TITLE")
    PR_NUMBER=$(gh pr create \
      --repo "$(git -C "$PROJECT_ROOT" remote get-url origin)" \
      --base main \
      --head "$EPIC_BRANCH" \
      --title "$EPIC_TITLE" \
      --body "$PR_BODY" \
      --json number \
      --jq '.number' 2>/dev/null || echo "")
    echo "Created PR #${PR_NUMBER} for epic ${EPIC_SLUG}"
  else
    PR_BODY=$("${SCRIPTS_DIR}/generate-pr-body.sh" "$PROJECT_ROOT" "$EPIC_SLUG" "$EPIC_TITLE")
    gh pr edit "$PR_NUMBER" --body "$PR_BODY" 2>/dev/null || true
    echo "Updated PR #${PR_NUMBER} body for epic ${EPIC_SLUG}"
  fi

  git -C "$PROJECT_ROOT" push origin "$EPIC_BRANCH"

  echo "MERGED:${STORY_BRANCH}:PR_NUMBER=${PR_NUMBER}"
done
