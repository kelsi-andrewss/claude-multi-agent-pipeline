#!/bin/bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: build-verify.sh --project-root <path> [--no-build]

Detect project type and run build/lint verification. Emits JSON results on stdout.

Supported project types: node_ts, flutter, python, rust, go.
Returns fail for unrecognized projects unless --no-build is passed.

Arguments:
  --project-root   Absolute path to the project root (required)
  --no-build       Explicitly opt out of build verification for projects with no recognized build system
  --help           Show this help message
USAGE
  exit 2
}

PROJECT_ROOT=""
NO_BUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --no-build) NO_BUILD=true; shift ;;
    --help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo "Error: --project-root is required" >&2
  usage
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': 'Project root does not exist: ' + sys.argv[1],
    'project_type': None,
    'build_cmd': None,
    'lint_cmd': None,
    'build_result': 'fail',
    'lint_warnings': 0
}))
" "$PROJECT_ROOT"
  exit 2
fi

cd "$PROJECT_ROOT"

# Detect project type (first match wins)
PROJECT_TYPE="unknown"
BUILD_CMD=""
LINT_CMD=""
TEST_CMD=""

if [[ -f "package.json" ]]; then
  PROJECT_TYPE="node_ts"
  read -r HAS_BUILD HAS_LINT <<< "$(python3 -c "
import json
with open('package.json') as f:
    pkg = json.load(f)
scripts = pkg.get('scripts', {})
has_build = '1' if 'build' in scripts else '0'
has_lint = '1' if 'lint' in scripts else '0'
print(has_build, has_lint)
")"
  if [[ "$HAS_BUILD" == "1" ]]; then
    BUILD_CMD="npm install && npm run build"
  else
    BUILD_CMD="npm install && npx tsc --noEmit"
  fi
  if [[ "$HAS_LINT" == "1" ]]; then
    LINT_CMD="npm run lint"
  fi
elif [[ -f "pubspec.yaml" ]]; then
  PROJECT_TYPE="flutter"
  BUILD_CMD="flutter pub get && flutter analyze"
elif [[ -f "pyproject.toml" ]]; then
  PROJECT_TYPE="python"
  BUILD_CMD="pip install -e . 2>&1 | tail -5"
  # Discover pytest: require both test files and a working pytest
  TEST_FILES=$(find . -maxdepth 4 -name 'test_*.py' -o -name '*_test.py' 2>/dev/null | head -1)
  if [[ -n "$TEST_FILES" ]] && python3 -m pytest --version >/dev/null 2>&1; then
    TEST_CMD="python3 -m pytest -x -q --tb=short"
  fi
elif [[ -f "Cargo.toml" ]]; then
  PROJECT_TYPE="rust"
  BUILD_CMD="cargo check && cargo clippy --quiet 2>&1"
elif [[ -f "go.mod" ]]; then
  PROJECT_TYPE="go"
  BUILD_CMD="go build ./... && go vet ./..."
fi

# If unknown project type, fail unless --no-build was passed
if [[ "$PROJECT_TYPE" == "unknown" ]]; then
  if [[ "$NO_BUILD" == "true" ]]; then
    python3 -c "
import json
print(json.dumps({
    'status': 'success',
    'project_type': 'unknown',
    'build_cmd': None,
    'lint_cmd': None,
    'build_result': 'skip',
    'lint_warnings': 0
}))
"
    exit 0
  else
    python3 -c "
import json
print(json.dumps({
    'status': 'error',
    'project_type': 'unknown',
    'build_cmd': None,
    'lint_cmd': None,
    'build_result': 'fail',
    'lint_warnings': 0,
    'build_output': 'No recognized build system. Pass --no-build to explicitly opt out of build verification.'
}))
"
    exit 1
  fi
fi

# Run build (disable errexit so we can capture non-zero exit codes)
echo "Running build: $BUILD_CMD" >&2
BUILD_OUTPUT=""
BUILD_EXIT=0
set +e
BUILD_OUTPUT=$(bash -c "$BUILD_CMD" 2>&1 | tail -30)
BUILD_EXIT=$?
set -e

if [[ $BUILD_EXIT -ne 0 ]]; then
  python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'project_type': sys.argv[1],
    'build_cmd': sys.argv[2],
    'lint_cmd': sys.argv[3] if sys.argv[3] else None,
    'build_result': 'fail',
    'build_output': sys.argv[4],
    'lint_warnings': 0
}))
" "$PROJECT_TYPE" "$BUILD_CMD" "${LINT_CMD:-}" "$BUILD_OUTPUT"
  exit 1
fi

# Run lint if available
LINT_WARNINGS=0
LINT_OUTPUT=""
if [[ -n "$LINT_CMD" ]]; then
  echo "Running lint: $LINT_CMD" >&2
  LINT_EXIT=0
  set +e
  LINT_OUTPUT=$(bash -c "$LINT_CMD" 2>&1)
  LINT_EXIT=$?
  set -e
  if [[ $LINT_EXIT -ne 0 ]]; then
    python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'project_type': sys.argv[1],
    'build_cmd': sys.argv[2],
    'lint_cmd': sys.argv[3],
    'build_result': 'fail',
    'lint_output': sys.argv[4],
    'lint_warnings': 0
}))
" "$PROJECT_TYPE" "$BUILD_CMD" "$LINT_CMD" "$LINT_OUTPUT"
    exit 1
  fi
  LINT_WARNINGS=$(echo "$LINT_OUTPUT" | grep -c -i "warning" || true)
fi

# Run tests if available (currently Python/pytest only)
TEST_OUTPUT=""
TEST_EXIT=0
if [[ -n "$TEST_CMD" ]]; then
  echo "Running tests: $TEST_CMD" >&2
  set +e
  TEST_OUTPUT=$(bash -c "$TEST_CMD" 2>&1 | tail -30)
  TEST_EXIT=$?
  set -e

  if [[ $TEST_EXIT -ne 0 ]]; then
    python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'project_type': sys.argv[1],
    'build_cmd': sys.argv[2],
    'lint_cmd': sys.argv[3] if sys.argv[3] else None,
    'test_cmd': sys.argv[4],
    'build_result': 'fail',
    'test_output': sys.argv[5],
    'lint_warnings': 0
}))
" "$PROJECT_TYPE" "$BUILD_CMD" "${LINT_CMD:-}" "$TEST_CMD" "$TEST_OUTPUT"
    exit 1
  fi
fi

# Emit success
python3 -c "
import json, sys
result = {
    'status': 'success',
    'project_type': sys.argv[1],
    'build_cmd': sys.argv[2],
    'lint_cmd': sys.argv[3] if sys.argv[3] else None,
    'build_result': 'pass',
    'lint_warnings': int(sys.argv[4])
}
if sys.argv[5]:
    result['test_cmd'] = sys.argv[5]
print(json.dumps(result))
" "$PROJECT_TYPE" "$BUILD_CMD" "${LINT_CMD:-}" "$LINT_WARNINGS" "${TEST_CMD:-}"
