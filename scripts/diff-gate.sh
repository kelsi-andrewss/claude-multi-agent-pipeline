#!/bin/bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: diff-gate.sh --worktree-path <path> --dev-branch <name> --write-files <comma-separated> [--blocking] [--test-files <comma-separated>]

Compare changed files in a worktree against the expected write_files manifest.
Reports unexpected changes as warnings (non-blocking by default).

Supports symbol annotations (e.g., "route.ts:queryPinecone") -- the :symbol
suffix is stripped before comparison.

Arguments:
  --worktree-path  Absolute path to the story worktree (required)
  --dev-branch     Branch to diff against (required)
  --write-files    Comma-separated list of expected changed files (required)
  --test-files     Comma-separated list of test file paths (optional). If any
                   changed file appears in this list, it is always a blocking violation.
  --blocking       Exit with code 1 if unexpected files are found (default: false)
  --help           Show this help message
USAGE
  exit 2
}

WORKTREE_PATH=""
DEV_BRANCH=""
WRITE_FILES=""
TEST_FILES=""
BLOCKING=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worktree-path) WORKTREE_PATH="$2"; shift 2 ;;
    --dev-branch) DEV_BRANCH="$2"; shift 2 ;;
    --write-files) WRITE_FILES="$2"; shift 2 ;;
    --test-files) TEST_FILES="$2"; shift 2 ;;
    --blocking) BLOCKING=true; shift ;;
    --help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$WORKTREE_PATH" || -z "$DEV_BRANCH" || -z "$WRITE_FILES" ]]; then
  echo "Error: all arguments are required" >&2
  usage
fi

if [[ ! -d "$WORKTREE_PATH" ]]; then
  python3 -c "
import json
print(json.dumps({
    'status': 'error',
    'error': 'Worktree path does not exist',
    'changed_files': [],
    'expected_files': [],
    'unexpected_files': []
}))
"
  exit 2
fi

# Get changed files (disable errexit to capture failure)
set +e
CHANGED_RAW=$(git -C "$WORKTREE_PATH" diff --name-only "$DEV_BRANCH" 2>&1)
DIFF_EXIT=$?
set -e

if [[ $DIFF_EXIT -ne 0 ]]; then
  python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': 'git diff failed: ' + sys.argv[1],
    'changed_files': [],
    'expected_files': [],
    'unexpected_files': []
}))
" "$CHANGED_RAW"
  exit 2
fi

# Compare using python for reliable JSON output and symbol stripping
set +e
python3 -c "
import json, sys

changed_raw = sys.argv[1]
write_files_raw = sys.argv[2]
blocking = sys.argv[3] == 'true'
test_files_raw = sys.argv[4]

# Parse changed files (one per line, skip empty)
changed = [f.strip() for f in changed_raw.split('\n') if f.strip()]

# Parse write_files: split on comma, strip :symbol suffix, deduplicate
expected = []
seen = set()
for entry in write_files_raw.split(','):
    entry = entry.strip()
    if not entry:
        continue
    # Strip symbol annotation (e.g., 'route.ts:queryPinecone' -> 'route.ts')
    filename = entry.split(':')[0] if ':' in entry else entry
    if filename not in seen:
        expected.append(filename)
        seen.add(filename)

# Parse test_files: comma-separated, strip whitespace
test_files_set = set()
for entry in test_files_raw.split(','):
    entry = entry.strip()
    if entry:
        test_files_set.add(entry)

# Find unexpected files
expected_set = set(expected)
unexpected = [f for f in changed if f not in expected_set]

# Find test file violations (changed files that are in test_files)
test_file_violations = [f for f in changed if f in test_files_set]

# Test file violations are always blocking, regardless of --blocking flag
blocked = (blocking and len(unexpected) > 0) or len(test_file_violations) > 0

print(json.dumps({
    'status': 'success',
    'changed_files': changed,
    'expected_files': expected,
    'unexpected_files': unexpected,
    'test_file_violations': test_file_violations,
    'blocking': blocking,
    'blocked': blocked
}))

# Exit 1 if blocked
sys.exit(1 if blocked else 0)
" "$CHANGED_RAW" "$WRITE_FILES" "$BLOCKING" "$TEST_FILES"
exit $?
