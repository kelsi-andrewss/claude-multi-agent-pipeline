#!/usr/bin/env bash
set -e

# merge-queue.sh
# Args: <project-root> '<json-manifest>'
# json-manifest is a JSON array of:
#   { storyBranch, storyTitle, epicSlug, epicTitle, prNumber, writeFiles }

PROJECT_ROOT="$1"
JSON_MANIFEST="$2"

if [ -z "$PROJECT_ROOT" ] || [ -z "$JSON_MANIFEST" ]; then
  echo "Usage: merge-queue.sh <project-root> '<json-manifest>'" >&2
  exit 1
fi

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse the manifest and iterate stories
COUNT=$(node -e "const m=JSON.parse(process.argv[1]); console.log(m.length);" -- "$JSON_MANIFEST")

# Track PR numbers per epic slug so they thread through across stories
declare -A EPIC_PR_NUMBERS

for i in $(seq 0 $((COUNT - 1))); do
  STORY_BRANCH=$(node -e "const m=JSON.parse(process.argv[1]); console.log(m[$i].storyBranch);" -- "$JSON_MANIFEST")
  STORY_TITLE=$(node -e "const m=JSON.parse(process.argv[1]); console.log(m[$i].storyTitle);" -- "$JSON_MANIFEST")
  EPIC_SLUG=$(node -e "const m=JSON.parse(process.argv[1]); console.log(m[$i].epicSlug);" -- "$JSON_MANIFEST")
  EPIC_TITLE=$(node -e "const m=JSON.parse(process.argv[1]); console.log(m[$i].epicTitle);" -- "$JSON_MANIFEST")
  PR_NUMBER=$(node -e "const m=JSON.parse(process.argv[1]); console.log(m[$i].prNumber || '');" -- "$JSON_MANIFEST")
  WRITE_FILES_JSON=$(node -e "const m=JSON.parse(process.argv[1]); console.log(JSON.stringify(m[$i].writeFiles));" -- "$JSON_MANIFEST")

  # Convert write-files JSON array to shell arguments
  readarray -t WRITE_FILES_ARR < <(node -e "const f=JSON.parse(process.argv[1]); f.forEach(x=>console.log(x));" -- "$WRITE_FILES_JSON")

  echo "--- Processing story: ${STORY_BRANCH} (epic: ${EPIC_SLUG}) ---"

  # Use previously discovered PR number for this epic if available
  if [ -n "${EPIC_PR_NUMBERS[$EPIC_SLUG]+_}" ] && [ "${EPIC_PR_NUMBERS[$EPIC_SLUG]}" != "" ]; then
    EFFECTIVE_PR="${EPIC_PR_NUMBERS[$EPIC_SLUG]}"
  else
    EFFECTIVE_PR="$PR_NUMBER"
  fi

  # Run diff gate
  bash "${SCRIPTS_DIR}/diff-gate.sh" \
    "$PROJECT_ROOT" \
    "$EPIC_SLUG" \
    "$STORY_BRANCH" \
    "${WRITE_FILES_ARR[@]}"

  # Run merge story — capture output to extract PR number
  MERGE_OUTPUT=$(bash "${SCRIPTS_DIR}/merge-story.sh" \
    "$PROJECT_ROOT" \
    "$EPIC_SLUG" \
    "$STORY_BRANCH" \
    "$STORY_TITLE" \
    "$EFFECTIVE_PR")

  echo "$MERGE_OUTPUT"

  # Extract PR number from MERGED line
  if echo "$MERGE_OUTPUT" | grep -q "^MERGED:"; then
    NEW_PR=$(echo "$MERGE_OUTPUT" | grep "^MERGED:" | sed 's/.*PR_NUMBER=//')
    if [ -n "$NEW_PR" ]; then
      EPIC_PR_NUMBERS["$EPIC_SLUG"]="$NEW_PR"
    fi
  fi
done

echo "merge-queue complete"
exit 0
