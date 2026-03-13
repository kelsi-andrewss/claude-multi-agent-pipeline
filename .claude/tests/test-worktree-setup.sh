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
  fi
  if [[ -n "${TMPDIR_BASE:-}" && -d "$TMPDIR_BASE" ]]; then
    rm -rf "$TMPDIR_BASE"
  fi
}
trap cleanup EXIT

# Create a bare repo to act as origin, then clone it
TMPDIR_BASE=$(mktemp -d /tmp/test-worktree-setup-XXXXXX)
BARE_REPO="$TMPDIR_BASE/origin.git"
TMPDIR_TEST="$TMPDIR_BASE/repo"

git init --bare -b main "$BARE_REPO" >&2 2>&1
git clone "$BARE_REPO" "$TMPDIR_TEST" >&2 2>&1
git -C "$TMPDIR_TEST" commit --allow-empty -m "init" >&2 2>&1
git -C "$TMPDIR_TEST" push origin main >&2 2>&1
git -C "$TMPDIR_TEST" branch dev >&2 2>&1
git -C "$TMPDIR_TEST" push origin dev >&2 2>&1

echo "=== Test 1: Happy path ===" >&2
WT_PATH="$TMPDIR_TEST/worktrees/test-branch"
OUTPUT=$("$SCRIPT_DIR/worktree-setup.sh" \
  --project-root "$TMPDIR_TEST" \
  --branch "test-branch" \
  --worktree-path "$WT_PATH" \
  --dev-branch "dev" 2>/dev/null)
EXIT_CODE=$?

assert_exit_code "$EXIT_CODE" "0" "T1: exit code"
assert_json_field "$OUTPUT" "status" "success" "T1: status"
assert_json_field "$OUTPUT" "verified" "True" "T1: verified"
assert_json_field "$OUTPUT" "branch" "test-branch" "T1: branch"

echo "=== Test 2: Branch already in another worktree ===" >&2
# test-branch is now checked out in WT_PATH, try a different worktree path
WT_PATH2="$TMPDIR_TEST/worktrees/test-branch-2"
set +e
OUTPUT2=$("$SCRIPT_DIR/worktree-setup.sh" \
  --project-root "$TMPDIR_TEST" \
  --branch "test-branch" \
  --worktree-path "$WT_PATH2" \
  --dev-branch "dev" 2>/dev/null)
EXIT_CODE2=$?
set -e

assert_exit_code "$EXIT_CODE2" "1" "T2: exit code"
assert_json_field "$OUTPUT2" "status" "error" "T2: status"

echo "=== Test 3: Worktree path already exists (idempotent) ===" >&2
# Same branch, same path -- should skip creation and succeed
OUTPUT3=$("$SCRIPT_DIR/worktree-setup.sh" \
  --project-root "$TMPDIR_TEST" \
  --branch "test-branch" \
  --worktree-path "$WT_PATH" \
  --dev-branch "dev" 2>/dev/null)
EXIT_CODE3=$?

assert_exit_code "$EXIT_CODE3" "0" "T3: exit code"
assert_json_field "$OUTPUT3" "status" "success" "T3: status"
assert_json_field "$OUTPUT3" "verified" "True" "T3: verified"

echo "=== Test 4: Missing arguments ===" >&2
set +e
OUTPUT4=$("$SCRIPT_DIR/worktree-setup.sh" --project-root "$TMPDIR_TEST" 2>/dev/null)
EXIT_CODE4=$?
set -e

assert_exit_code "$EXIT_CODE4" "2" "T4: exit code"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ -n "$ERRORS" ]] && printf "$ERRORS"
exit "$FAIL"
