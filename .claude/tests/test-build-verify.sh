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
    rm -rf "$TMPDIR_TEST"
  fi
}
trap cleanup EXIT

TMPDIR_TEST=$(mktemp -d /tmp/test-build-verify-XXXXXX)

echo "=== Test 1: Node project with build script ===" >&2
PROJ1="$TMPDIR_TEST/node-project"
mkdir -p "$PROJ1"
cat > "$PROJ1/package.json" <<'EOF'
{
  "name": "test",
  "scripts": {
    "build": "echo build-ok",
    "lint": "echo lint-ok"
  }
}
EOF

OUTPUT=$("$SCRIPT_DIR/build-verify.sh" --project-root "$PROJ1" 2>/dev/null)
EXIT_CODE=$?

assert_exit_code "$EXIT_CODE" "0" "T1: exit code"
assert_json_field "$OUTPUT" "status" "success" "T1: status"
assert_json_field "$OUTPUT" "project_type" "node_ts" "T1: project_type"
assert_json_field "$OUTPUT" "build_result" "pass" "T1: build_result"

echo "=== Test 2: No recognized project type ===" >&2
PROJ2="$TMPDIR_TEST/empty-project"
mkdir -p "$PROJ2"

OUTPUT2=$("$SCRIPT_DIR/build-verify.sh" --project-root "$PROJ2" 2>/dev/null)
EXIT_CODE2=$?

assert_exit_code "$EXIT_CODE2" "0" "T2: exit code"
assert_json_field "$OUTPUT2" "status" "success" "T2: status"
assert_json_field "$OUTPUT2" "project_type" "unknown" "T2: project_type"
assert_json_field "$OUTPUT2" "build_result" "skip" "T2: build_result"

echo "=== Test 3: Build failure ===" >&2
PROJ3="$TMPDIR_TEST/failing-project"
mkdir -p "$PROJ3"
cat > "$PROJ3/package.json" <<'EOF'
{
  "name": "test-fail",
  "scripts": {
    "build": "echo 'src/index.ts(42): Cannot find module' && exit 1"
  }
}
EOF

set +e
OUTPUT3=$("$SCRIPT_DIR/build-verify.sh" --project-root "$PROJ3" 2>/dev/null)
EXIT_CODE3=$?
set -e

assert_exit_code "$EXIT_CODE3" "1" "T3: exit code"
assert_json_field "$OUTPUT3" "status" "error" "T3: status"
assert_json_field "$OUTPUT3" "build_result" "fail" "T3: build_result"
# Verify build_output is populated
HAS_OUTPUT=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('yes' if d.get('build_output') else 'no')" "$OUTPUT3")
if [[ "$HAS_OUTPUT" == "yes" ]]; then
  ((++PASS))
else
  ((++FAIL)) || true
  ERRORS+="  FAIL: T3: build_output should be populated\n"
fi

echo "=== Test 4: Multiple marker files (package.json + pyproject.toml) -- picks first ===" >&2
PROJ4="$TMPDIR_TEST/multi-project"
mkdir -p "$PROJ4"
cat > "$PROJ4/package.json" <<'EOF'
{
  "name": "test-multi",
  "scripts": {
    "build": "echo multi-ok"
  }
}
EOF
touch "$PROJ4/pyproject.toml"

OUTPUT4=$("$SCRIPT_DIR/build-verify.sh" --project-root "$PROJ4" 2>/dev/null)
EXIT_CODE4=$?

assert_exit_code "$EXIT_CODE4" "0" "T4: exit code"
assert_json_field "$OUTPUT4" "project_type" "node_ts" "T4: project_type (first match)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ -n "$ERRORS" ]] && printf "$ERRORS"
exit "$FAIL"
