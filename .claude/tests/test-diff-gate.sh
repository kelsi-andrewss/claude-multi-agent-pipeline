#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)/scripts"
PASS=0; FAIL=0; ERRORS=""

assert_json_field() {
  local json="$1" field="$2" expected="$3" label="$4"
  actual=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('$field','__MISSING__'))" "$json")
  if [[ "$actual" == "$expected" ]]; then
    ((++PASS))
  else
    ((++FAIL)) || true
    ERRORS+="  FAIL: $label -- expected '$expected', got '$actual'\n"
  fi
}

assert_json_array_len() {
  local json="$1" field="$2" expected="$3" label="$4"
  actual=$(python3 -c "import json,sys; print(len(json.loads(sys.argv[1]).get('$field',[])))" "$json")
  if [[ "$actual" == "$expected" ]]; then
    ((++PASS))
  else
    ((++FAIL)) || true
    ERRORS+="  FAIL: $label -- expected array length $expected, got $actual\n"
  fi
}

assert_exit_code() {
  local actual="$1" expected="$2" label="$3"
  if [[ "$actual" == "$expected" ]]; then
    ((++PASS))
  else
    ((++FAIL)) || true
    ERRORS+="  FAIL: $label -- expected exit $expected, got $actual\n"
  fi
}

cleanup() {
  if [[ -n "${TMPDIR_TEST:-}" && -d "$TMPDIR_TEST" ]]; then
    git -C "$TMPDIR_TEST" worktree prune 2>/dev/null || true
    rm -rf "$TMPDIR_TEST"
  fi
}
trap cleanup EXIT

# Create a temp git repo with dev branch and a worktree
TMPDIR_TEST=$(mktemp -d /tmp/test-diff-gate-XXXXXX)
git -C "$TMPDIR_TEST" init -b main >&2 2>&1
echo "base" > "$TMPDIR_TEST/base.txt"
git -C "$TMPDIR_TEST" add base.txt >&2 2>&1
git -C "$TMPDIR_TEST" commit -m "init" >&2 2>&1
git -C "$TMPDIR_TEST" branch dev >&2 2>&1

# Create a story branch with some changes
git -C "$TMPDIR_TEST" branch story-branch >&2 2>&1
WT_PATH="$TMPDIR_TEST/worktrees/story"
git -C "$TMPDIR_TEST" worktree add "$WT_PATH" story-branch >&2 2>&1

echo "=== Test 1: All changed files expected ===" >&2
mkdir -p "$WT_PATH/src"
echo "new content" > "$WT_PATH/src/app.ts"
echo "utils" > "$WT_PATH/src/utils.ts"
git -C "$WT_PATH" add src/app.ts src/utils.ts >&2 2>&1
git -C "$WT_PATH" commit -m "add files" >&2 2>&1

OUTPUT=$("$SCRIPT_DIR/diff-gate.sh" \
  --worktree-path "$WT_PATH" \
  --dev-branch "dev" \
  --write-files "src/app.ts,src/utils.ts" 2>/dev/null)
EXIT_CODE=$?

assert_exit_code "$EXIT_CODE" "0" "T1: exit code"
assert_json_field "$OUTPUT" "status" "success" "T1: status"
assert_json_array_len "$OUTPUT" "unexpected_files" "0" "T1: no unexpected files"
assert_json_array_len "$OUTPUT" "changed_files" "2" "T1: 2 changed files"

echo "=== Test 2: Extra files changed ===" >&2
echo "config" > "$WT_PATH/src/config.ts"
git -C "$WT_PATH" add src/config.ts >&2 2>&1
git -C "$WT_PATH" commit -m "add config" >&2 2>&1

OUTPUT2=$("$SCRIPT_DIR/diff-gate.sh" \
  --worktree-path "$WT_PATH" \
  --dev-branch "dev" \
  --write-files "src/app.ts,src/utils.ts" 2>/dev/null)
EXIT_CODE2=$?

assert_exit_code "$EXIT_CODE2" "0" "T2: exit code (still 0, non-blocking)"
assert_json_field "$OUTPUT2" "status" "success" "T2: status"
assert_json_array_len "$OUTPUT2" "unexpected_files" "1" "T2: 1 unexpected file"

echo "=== Test 3: Symbol annotations stripped ===" >&2
OUTPUT3=$("$SCRIPT_DIR/diff-gate.sh" \
  --worktree-path "$WT_PATH" \
  --dev-branch "dev" \
  --write-files "src/app.ts:queryPinecone,src/utils.ts:helper,src/config.ts" 2>/dev/null)
EXIT_CODE3=$?

assert_exit_code "$EXIT_CODE3" "0" "T3: exit code"
assert_json_field "$OUTPUT3" "status" "success" "T3: status"
assert_json_array_len "$OUTPUT3" "unexpected_files" "0" "T3: no unexpected after symbol stripping"
assert_json_array_len "$OUTPUT3" "expected_files" "3" "T3: 3 expected files (deduped)"

echo "=== Test 4: No changes ===" >&2
# Create a fresh worktree with no changes from dev
git -C "$TMPDIR_TEST" branch empty-branch dev >&2 2>&1
WT_EMPTY="$TMPDIR_TEST/worktrees/empty"
git -C "$TMPDIR_TEST" worktree add "$WT_EMPTY" empty-branch >&2 2>&1

OUTPUT4=$("$SCRIPT_DIR/diff-gate.sh" \
  --worktree-path "$WT_EMPTY" \
  --dev-branch "dev" \
  --write-files "src/app.ts" 2>/dev/null)
EXIT_CODE4=$?

assert_exit_code "$EXIT_CODE4" "0" "T4: exit code"
assert_json_field "$OUTPUT4" "status" "success" "T4: status"
assert_json_array_len "$OUTPUT4" "changed_files" "0" "T4: 0 changed files"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ -n "$ERRORS" ]] && printf "$ERRORS"
exit "$FAIL"
