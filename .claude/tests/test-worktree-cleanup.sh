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

# Create a temp git repo
TMPDIR_TEST=$(mktemp -d /tmp/test-worktree-cleanup-XXXXXX)
git -C "$TMPDIR_TEST" init -b main >&2 2>&1
git -C "$TMPDIR_TEST" commit --allow-empty -m "init" >&2 2>&1

echo "=== Test 1: Happy path -- remove worktree and branch ===" >&2
git -C "$TMPDIR_TEST" branch cleanup-branch >&2 2>&1
WT_PATH="$TMPDIR_TEST/worktrees/cleanup-test"
git -C "$TMPDIR_TEST" worktree add "$WT_PATH" cleanup-branch >&2 2>&1

OUTPUT=$("$SCRIPT_DIR/worktree-cleanup.sh" \
  --worktree-path "$WT_PATH" \
  --branch "cleanup-branch" \
  --force 2>/dev/null)
EXIT_CODE=$?

assert_exit_code "$EXIT_CODE" "0" "T1: exit code"
assert_json_field "$OUTPUT" "status" "success" "T1: status"
assert_json_field "$OUTPUT" "removed_worktree" "True" "T1: removed_worktree"
assert_json_field "$OUTPUT" "removed_branch" "True" "T1: removed_branch"

echo "=== Test 2: Stale worktree (already removed from disk) ===" >&2
git -C "$TMPDIR_TEST" branch stale-branch >&2 2>&1
WT_PATH2="$TMPDIR_TEST/worktrees/stale-test"
git -C "$TMPDIR_TEST" worktree add "$WT_PATH2" stale-branch >&2 2>&1
# Remove the directory manually to simulate stale state
rm -rf "$WT_PATH2"

OUTPUT2=$("$SCRIPT_DIR/worktree-cleanup.sh" \
  --worktree-path "$WT_PATH2" \
  --force 2>/dev/null)
EXIT_CODE2=$?

assert_exit_code "$EXIT_CODE2" "0" "T2: exit code"
assert_json_field "$OUTPUT2" "status" "success" "T2: status"
assert_json_field "$OUTPUT2" "removed_worktree" "True" "T2: removed_worktree"

echo "=== Test 3: No --branch flag -- only removes worktree ===" >&2
git -C "$TMPDIR_TEST" branch nobranch-test >&2 2>&1
WT_PATH3="$TMPDIR_TEST/worktrees/nobranch-test"
git -C "$TMPDIR_TEST" worktree add "$WT_PATH3" nobranch-test >&2 2>&1

OUTPUT3=$("$SCRIPT_DIR/worktree-cleanup.sh" \
  --worktree-path "$WT_PATH3" \
  --force 2>/dev/null)
EXIT_CODE3=$?

assert_exit_code "$EXIT_CODE3" "0" "T3: exit code"
assert_json_field "$OUTPUT3" "status" "success" "T3: status"
assert_json_field "$OUTPUT3" "removed_worktree" "True" "T3: removed_worktree"
assert_json_field "$OUTPUT3" "removed_branch" "False" "T3: removed_branch"

echo "=== Test 4: Dirty worktree without --force ===" >&2
git -C "$TMPDIR_TEST" branch dirty-branch >&2 2>&1
WT_PATH4="$TMPDIR_TEST/worktrees/dirty-test"
git -C "$TMPDIR_TEST" worktree add "$WT_PATH4" dirty-branch >&2 2>&1
echo "dirty file" > "$WT_PATH4/untracked.txt"
git -C "$WT_PATH4" add untracked.txt >&2 2>&1

set +e
OUTPUT4=$("$SCRIPT_DIR/worktree-cleanup.sh" \
  --worktree-path "$WT_PATH4" 2>/dev/null)
EXIT_CODE4=$?
set -e

assert_exit_code "$EXIT_CODE4" "1" "T4: exit code"
assert_json_field "$OUTPUT4" "status" "error" "T4: status"
assert_json_field "$OUTPUT4" "removed_worktree" "False" "T4: removed_worktree"

echo "=== Test 5: Dirty worktree WITH --force ===" >&2
OUTPUT5=$("$SCRIPT_DIR/worktree-cleanup.sh" \
  --worktree-path "$WT_PATH4" \
  --force 2>/dev/null)
EXIT_CODE5=$?

assert_exit_code "$EXIT_CODE5" "0" "T5: exit code"
assert_json_field "$OUTPUT5" "status" "success" "T5: status"
assert_json_field "$OUTPUT5" "removed_worktree" "True" "T5: removed_worktree"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ -n "$ERRORS" ]] && printf "$ERRORS"
exit "$FAIL"
