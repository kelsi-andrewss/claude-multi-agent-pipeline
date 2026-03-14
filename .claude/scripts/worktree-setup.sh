#!/bin/bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: worktree-setup.sh --project-root <path> --branch <name> --worktree-path <path> --dev-branch <name>

Create a git worktree for a story branch, with retry-with-backoff for index.lock contention.

Arguments:
  --project-root   Absolute path to the git repo root
  --branch         Story branch name to create/checkout
  --worktree-path  Absolute path for the new worktree
  --dev-branch     Base branch to create the story branch from
  --help           Show this help message
USAGE
  exit 2
}

PROJECT_ROOT=""
BRANCH=""
WORKTREE_PATH=""
DEV_BRANCH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --worktree-path) WORKTREE_PATH="$2"; shift 2 ;;
    --dev-branch) DEV_BRANCH="$2"; shift 2 ;;
    --help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$PROJECT_ROOT" || -z "$BRANCH" || -z "$WORKTREE_PATH" || -z "$DEV_BRANCH" ]]; then
  echo "Error: all arguments are required" >&2
  usage
fi

emit_result() {
  python3 -c "
import json, sys
data = json.loads(sys.argv[1])
print(json.dumps(data))
" "$1"
}

emit_error() {
  local msg="$1"
  local exit_code="${2:-1}"
  python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': sys.argv[1],
    'worktree_path': sys.argv[2],
    'branch': sys.argv[3],
    'verified': False
}))
" "$msg" "$WORKTREE_PATH" "$BRANCH"
  exit "$exit_code"
}

if [[ ! -d "$PROJECT_ROOT" ]]; then
  emit_error "Cannot cd to project root: $PROJECT_ROOT" 2
fi

cd "$PROJECT_ROOT"

echo "Fetching origin/$DEV_BRANCH..." >&2
if ! git fetch origin "$DEV_BRANCH" >&2 2>&1; then
  emit_error "Failed to fetch origin/$DEV_BRANCH" 2
fi

# Check if branch is already checked out in another worktree
# Porcelain format: "worktree <path>\nHEAD <hash>\nbranch <ref>\n" -- need -B2 to reach worktree line
EXISTING_WT=$(git worktree list --porcelain 2>/dev/null | grep -B2 "branch refs/heads/$BRANCH" | head -1 | sed 's/^worktree //' || true)
# Normalize both paths for comparison (macOS /tmp -> /private/tmp)
EXISTING_WT_REAL=$(cd "$EXISTING_WT" 2>/dev/null && pwd -P || echo "$EXISTING_WT")
WORKTREE_PATH_REAL=$(cd "$WORKTREE_PATH" 2>/dev/null && pwd -P || echo "$WORKTREE_PATH")
if [[ -n "$EXISTING_WT" && "$EXISTING_WT_REAL" != "$WORKTREE_PATH_REAL" ]]; then
  emit_error "Branch $BRANCH is already checked out in another worktree: $EXISTING_WT" 1
fi

# Create branch if it doesn't exist
if ! git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "Creating branch $BRANCH from $DEV_BRANCH..." >&2
  git branch "$BRANCH" "$DEV_BRANCH" >&2 2>&1
fi

# Check if worktree already exists at this path (check for .git file that marks a worktree)
if [[ -d "$WORKTREE_PATH" && -f "$WORKTREE_PATH/.git" ]]; then
  echo "Worktree already exists at $WORKTREE_PATH, skipping creation." >&2
else
  # Add worktree with retry-with-backoff (3 attempts) for index.lock contention
  MAX_ATTEMPTS=3
  ATTEMPT=0
  while true; do
    ((ATTEMPT++)) || true
    echo "Adding worktree (attempt $ATTEMPT/$MAX_ATTEMPTS)..." >&2
    if git worktree add "$WORKTREE_PATH" "$BRANCH" >&2 2>&1; then
      break
    fi
    if [[ $ATTEMPT -ge $MAX_ATTEMPTS ]]; then
      emit_error "Failed to add worktree after $MAX_ATTEMPTS attempts (possible index.lock contention)" 1
    fi
    echo "Retrying in ${ATTEMPT}s (possible index.lock contention)..." >&2
    sleep "$ATTEMPT"
  done
fi

# Verify branch in worktree
ACTUAL_BRANCH=$(git -C "$WORKTREE_PATH" branch --show-current 2>/dev/null || true)
if [[ "$ACTUAL_BRANCH" == "$BRANCH" ]]; then
  VERIFIED="True"
else
  VERIFIED="False"
fi

python3 -c "
import json, sys
print(json.dumps({
    'status': 'success',
    'worktree_path': sys.argv[1],
    'branch': sys.argv[2],
    'verified': sys.argv[3] == 'True'
}))
" "$WORKTREE_PATH" "$BRANCH" "$VERIFIED"
