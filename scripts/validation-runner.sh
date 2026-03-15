#!/bin/bash
set -euo pipefail

# validation-runner.sh — Validation pyramid for fix-loop
# Detects project type and runs compile/lint/test layers in gated sequence.
# Returns unified JSON with per-layer results.
#
# Usage:
#   validation-runner.sh --project-root <path> [--layer compile|lint|test|all]
#
# Layers are strictly gated: compile must pass before lint runs, lint before tests.
# When --layer specifies a single layer, only that layer runs (no gating).

usage() {
  cat >&2 <<'USAGE'
Usage: validation-runner.sh --project-root <path> [--layer compile|lint|test|all]

Run the validation pyramid against a project directory.

Arguments:
  --project-root   Absolute path to the project root (required)
  --layer          Which layer(s) to run: compile, lint, test, or all (default: all)
  --help           Show this help message
USAGE
  exit 2
}

PROJECT_ROOT=""
LAYER="all"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --layer) LAYER="$2"; shift 2 ;;
    --help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo '{"error": "--project-root is required", "overall_status": "error"}'
  exit 2
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "{\"error\": \"Project root does not exist: $PROJECT_ROOT\", \"overall_status\": \"error\"}"
  exit 2
fi

case "$LAYER" in
  compile|lint|test|all) ;;
  *) echo "{\"error\": \"Invalid --layer: $LAYER. Must be compile, lint, test, or all\", \"overall_status\": \"error\"}"; exit 2 ;;
esac

cd "$PROJECT_ROOT"

# --- Project type detection ---
PROJECT_TYPE="unknown"

if [[ -f "pubspec.yaml" ]]; then
  PROJECT_TYPE="flutter"
elif [[ -f "package.json" ]]; then
  PROJECT_TYPE="node_ts"
elif [[ -f "Cargo.toml" ]]; then
  PROJECT_TYPE="rust"
elif [[ -f "go.mod" ]]; then
  PROJECT_TYPE="go"
elif [[ -f "pyproject.toml" ]] || [[ -f "requirements.txt" ]] || [[ -f "setup.py" ]]; then
  PROJECT_TYPE="python"
fi

if [[ "$PROJECT_TYPE" == "unknown" ]]; then
  python3 -c "
import json
print(json.dumps({
    'project_type': 'unknown',
    'layers': [],
    'overall_status': 'skip'
}))
"
  exit 0
fi

# --- Layer runner helpers ---
# Each run_*_layer function sets LAYER_STATUS, LAYER_OUTPUT, LAYER_ERROR_COUNT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run_compile_layer() {
  local exit_code=0
  local output=""

  # Delegate to build-verify.sh for compile detection
  if [[ -f "$SCRIPT_DIR/build-verify.sh" ]]; then
    set +e
    output=$(bash "$SCRIPT_DIR/build-verify.sh" --project-root "$PROJECT_ROOT" 2>/dev/null)
    exit_code=$?
    set -e

    # Parse build-verify.sh JSON result
    local build_result
    build_result=$(echo "$output" | python3 -c "import json,sys; print(json.load(sys.stdin).get('build_result','fail'))" 2>/dev/null || echo "fail")

    if [[ "$build_result" == "pass" ]] || [[ "$build_result" == "skip" ]]; then
      LAYER_STATUS="pass"
      LAYER_OUTPUT="$output"
      LAYER_ERROR_COUNT=0
    else
      LAYER_STATUS="fail"
      local build_output
      build_output=$(echo "$output" | python3 -c "import json,sys; print(json.load(sys.stdin).get('build_output','Build failed'))" 2>/dev/null || echo "$output")
      LAYER_OUTPUT="$build_output"
      LAYER_ERROR_COUNT=$(echo "$build_output" | grep -c -iE "error|Error" || true)
      [[ "$LAYER_ERROR_COUNT" -eq 0 ]] && LAYER_ERROR_COUNT=1
    fi
  else
    # Fallback: run compile commands directly
    case "$PROJECT_TYPE" in
      flutter)
        set +e; output=$(flutter pub get && flutter analyze 2>&1); exit_code=$?; set -e ;;
      node_ts)
        local has_build
        has_build=$(python3 -c "import json; print('1' if 'build' in json.load(open('package.json')).get('scripts',{}) else '0')" 2>/dev/null || echo "0")
        if [[ "$has_build" == "1" ]]; then
          set +e; output=$(npm install --silent && npm run build 2>&1 | tail -30); exit_code=$?; set -e
        else
          set +e; output=$(npm install --silent && npx tsc --noEmit 2>&1 | tail -30); exit_code=$?; set -e
        fi ;;
      python)
        set +e; output=$(python3 -m py_compile $(find . -name "*.py" -not -path "./.venv/*" -not -path "./venv/*" | head -50) 2>&1); exit_code=$?; set -e ;;
      rust)
        set +e; output=$(cargo check 2>&1 | tail -30); exit_code=$?; set -e ;;
      go)
        set +e; output=$(go build ./... 2>&1 | tail -30); exit_code=$?; set -e ;;
    esac

    if [[ $exit_code -eq 0 ]]; then
      LAYER_STATUS="pass"
      LAYER_OUTPUT="$output"
      LAYER_ERROR_COUNT=0
    else
      LAYER_STATUS="fail"
      LAYER_OUTPUT="$output"
      LAYER_ERROR_COUNT=$(echo "$output" | grep -c -iE "error|Error" || true)
      [[ "$LAYER_ERROR_COUNT" -eq 0 ]] && LAYER_ERROR_COUNT=1
    fi
  fi
}

run_lint_layer() {
  local exit_code=0
  local output=""

  case "$PROJECT_TYPE" in
    flutter)
      set +e; output=$(flutter analyze 2>&1); exit_code=$?; set -e ;;
    node_ts)
      local has_lint
      has_lint=$(python3 -c "import json; print('1' if 'lint' in json.load(open('package.json')).get('scripts',{}) else '0')" 2>/dev/null || echo "0")
      if [[ "$has_lint" == "1" ]]; then
        set +e; output=$(npm run lint 2>&1); exit_code=$?; set -e
      else
        # Try common linters
        if command -v npx &>/dev/null && [[ -f ".eslintrc.js" ]] || [[ -f ".eslintrc.json" ]] || [[ -f ".eslintrc.yml" ]] || [[ -f "eslint.config.js" ]] || [[ -f "eslint.config.mjs" ]]; then
          set +e; output=$(npx eslint . 2>&1); exit_code=$?; set -e
        else
          output="No lint configuration found"
          exit_code=0
        fi
      fi ;;
    python)
      if command -v ruff &>/dev/null; then
        set +e; output=$(ruff check . 2>&1); exit_code=$?; set -e
      elif command -v flake8 &>/dev/null; then
        set +e; output=$(flake8 . 2>&1); exit_code=$?; set -e
      elif command -v pylint &>/dev/null; then
        set +e; output=$(pylint --recursive=y . 2>&1 | tail -30); exit_code=$?; set -e
      else
        output="No Python linter found (tried ruff, flake8, pylint)"
        exit_code=0
      fi ;;
    rust)
      set +e; output=$(cargo clippy --quiet 2>&1 | tail -30); exit_code=$?; set -e ;;
    go)
      set +e; output=$(go vet ./... 2>&1); exit_code=$?; set -e ;;
  esac

  if [[ $exit_code -eq 0 ]]; then
    LAYER_STATUS="pass"
    LAYER_OUTPUT="$output"
    LAYER_ERROR_COUNT=0
  else
    LAYER_STATUS="fail"
    LAYER_OUTPUT="$output"
    LAYER_ERROR_COUNT=$(echo "$output" | grep -c -iE "error|warning|Error|Warning" || true)
    [[ "$LAYER_ERROR_COUNT" -eq 0 ]] && LAYER_ERROR_COUNT=1
  fi
}

run_test_layer() {
  local exit_code=0
  local output=""

  case "$PROJECT_TYPE" in
    flutter)
      set +e; output=$(flutter test 2>&1 | tail -50); exit_code=$?; set -e ;;
    node_ts)
      local has_test
      has_test=$(python3 -c "import json; s=json.load(open('package.json')).get('scripts',{}); print('1' if 'test' in s and s['test'] != 'echo \\\"Error: no test specified\\\" && exit 1' else '0')" 2>/dev/null || echo "0")
      if [[ "$has_test" == "1" ]]; then
        set +e; output=$(npm test 2>&1 | tail -50); exit_code=$?; set -e
      else
        output="No test script configured"
        exit_code=0
      fi ;;
    python)
      if [[ -f "pytest.ini" ]] || [[ -f "pyproject.toml" ]] || [[ -d "tests" ]] || [[ -d "test" ]]; then
        set +e; output=$(python3 -m pytest --tb=short 2>&1 | tail -50); exit_code=$?; set -e
      else
        output="No test configuration found"
        exit_code=0
      fi ;;
    rust)
      set +e; output=$(cargo test 2>&1 | tail -50); exit_code=$?; set -e ;;
    go)
      set +e; output=$(go test ./... 2>&1 | tail -50); exit_code=$?; set -e ;;
  esac

  if [[ $exit_code -eq 0 ]]; then
    LAYER_STATUS="pass"
    LAYER_OUTPUT="$output"
    LAYER_ERROR_COUNT=0
  else
    LAYER_STATUS="fail"
    LAYER_OUTPUT="$output"
    LAYER_ERROR_COUNT=$(echo "$output" | grep -c -iE "FAIL|fail|error|Error" || true)
    [[ "$LAYER_ERROR_COUNT" -eq 0 ]] && LAYER_ERROR_COUNT=1
  fi
}

# --- Execute requested layers ---

# Layer result accumulators
COMPILE_JSON='{"name":"compile","status":"skip","output":"","error_count":0}'
LINT_JSON='{"name":"lint","status":"skip","output":"","error_count":0}'
TEST_JSON='{"name":"test","status":"skip","output":"","error_count":0}'
OVERALL="pass"
GATED_STOP=false

escape_json_string() {
  python3 -c "import json,sys; print(json.dumps(sys.stdin.read().rstrip()))" <<< "$1"
}

run_and_record_compile() {
  if [[ "$GATED_STOP" == true ]]; then return; fi
  run_compile_layer
  local escaped_output
  escaped_output=$(escape_json_string "$LAYER_OUTPUT")
  COMPILE_JSON="{\"name\":\"compile\",\"status\":\"$LAYER_STATUS\",\"output\":$escaped_output,\"error_count\":$LAYER_ERROR_COUNT}"
  if [[ "$LAYER_STATUS" == "fail" ]]; then
    OVERALL="fail"
    GATED_STOP=true
  fi
}

run_and_record_lint() {
  if [[ "$GATED_STOP" == true ]]; then return; fi
  run_lint_layer
  local escaped_output
  escaped_output=$(escape_json_string "$LAYER_OUTPUT")
  LINT_JSON="{\"name\":\"lint\",\"status\":\"$LAYER_STATUS\",\"output\":$escaped_output,\"error_count\":$LAYER_ERROR_COUNT}"
  if [[ "$LAYER_STATUS" == "fail" ]]; then
    OVERALL="fail"
    GATED_STOP=true
  fi
}

run_and_record_test() {
  if [[ "$GATED_STOP" == true ]]; then return; fi
  run_test_layer
  local escaped_output
  escaped_output=$(escape_json_string "$LAYER_OUTPUT")
  TEST_JSON="{\"name\":\"test\",\"status\":\"$LAYER_STATUS\",\"output\":$escaped_output,\"error_count\":$LAYER_ERROR_COUNT}"
  if [[ "$LAYER_STATUS" == "fail" ]]; then
    OVERALL="fail"
  fi
}

case "$LAYER" in
  compile)
    run_and_record_compile
    ;;
  lint)
    run_and_record_lint
    ;;
  test)
    run_and_record_test
    ;;
  all)
    run_and_record_compile
    run_and_record_lint
    run_and_record_test
    ;;
esac

# --- Emit unified JSON result ---
echo "{\"project_type\":\"$PROJECT_TYPE\",\"layers\":[$COMPILE_JSON,$LINT_JSON,$TEST_JSON],\"overall_status\":\"$OVERALL\"}"
