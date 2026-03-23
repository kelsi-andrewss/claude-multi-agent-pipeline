#!/usr/bin/env bash
# test-diagnosis.sh — Run failing tests against dev branch to attribute failure
# to code regression vs invalid test.
#
# Usage:
#   bash test-diagnosis.sh --worktree-path <path> --dev-branch <branch> \
#     --test-cmd <cmd> --test-files <files> --story-branch <branch>
#
# Exit codes:
#   0 = diagnosis complete (check JSON output)
#   2 = system error

set -euo pipefail

WORKTREE_PATH=""
DEV_BRANCH=""
TEST_CMD=""
TEST_FILES=""
STORY_BRANCH=""
TEMP_WORKTREE=""

cleanup() {
  if [ -n "$TEMP_WORKTREE" ] && [ -d "$TEMP_WORKTREE" ]; then
    git worktree remove --force "$TEMP_WORKTREE" 2>/dev/null || true
    rm -rf "$TEMP_WORKTREE" 2>/dev/null || true
  fi
}
trap cleanup EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worktree-path) WORKTREE_PATH="$2"; shift 2 ;;
    --dev-branch) DEV_BRANCH="$2"; shift 2 ;;
    --test-cmd) TEST_CMD="$2"; shift 2 ;;
    --test-files) TEST_FILES="$2"; shift 2 ;;
    --story-branch) STORY_BRANCH="$2"; shift 2 ;;
    --help)
      echo "Usage: test-diagnosis.sh --worktree-path <path> --dev-branch <branch> --test-cmd <cmd> --test-files <files> --story-branch <branch>"
      exit 0
      ;;
    *) echo "{\"diagnosis\": \"inconclusive\", \"detail\": \"Unknown argument: $1\"}"; exit 2 ;;
  esac
done

if [ -z "$WORKTREE_PATH" ] || [ -z "$DEV_BRANCH" ] || [ -z "$TEST_CMD" ] || [ -z "$TEST_FILES" ]; then
  echo '{"diagnosis": "inconclusive", "detail": "Missing required arguments. Need: --worktree-path, --dev-branch, --test-cmd, --test-files"}'
  exit 2
fi

# Create temp worktree from dev branch (without story changes)
TEMP_WORKTREE=$(mktemp -d /tmp/test-diag-XXXXXX)
rm -rf "$TEMP_WORKTREE"

if ! git worktree add "$TEMP_WORKTREE" "$DEV_BRANCH" 2>/dev/null; then
  echo "{\"diagnosis\": \"inconclusive\", \"detail\": \"Could not create temp worktree from $DEV_BRANCH\"}"
  exit 0
fi

# Copy test files from the story worktree into the dev-only worktree
# (tests exist on the story branch, not on dev)
IFS=',' read -ra FILE_LIST <<< "$TEST_FILES"
for f in "${FILE_LIST[@]}"; do
  f=$(echo "$f" | xargs)  # trim whitespace
  if [ -f "$WORKTREE_PATH/$f" ]; then
    mkdir -p "$TEMP_WORKTREE/$(dirname "$f")"
    cp "$WORKTREE_PATH/$f" "$TEMP_WORKTREE/$f"
  fi
done

# Run the failing tests against dev-only code
TEST_OUTPUT=""
TEST_EXIT=0
if ! TEST_OUTPUT=$(cd "$TEMP_WORKTREE" && eval "$TEST_CMD $TEST_FILES" 2>&1); then
  TEST_EXIT=$?
fi

if [ $TEST_EXIT -ne 0 ]; then
  # Test also fails on dev — the test itself is invalid
  DETAIL=$(echo "$TEST_OUTPUT" | tail -5 | tr '\n' ' ' | sed 's/"/\\"/g')
  echo "{\"diagnosis\": \"test_invalid\", \"detail\": \"Test fails on dev branch without story changes: $DETAIL\"}"
else
  # Test passes on dev but fails with story changes — code regression
  echo "{\"diagnosis\": \"code_regression\", \"detail\": \"Test passes on dev but fails with story changes\"}"
fi

exit 0
