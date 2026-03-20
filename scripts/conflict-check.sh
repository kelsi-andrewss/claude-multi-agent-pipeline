#!/bin/bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: conflict-check.sh --branch-a <ref> --branch-b <ref> [--base <ref>] [--project-root <path>]

Two-tier conflict detection between git branches.
Tier 1: git merge-tree simulation (textual conflicts).
Tier 2: symbol-level grep analysis (same vs different symbols).

Emits JSON results on stdout.

Arguments:
  --branch-a       First branch/ref to check (required)
  --branch-b       Second branch/ref to check (required)
  --base           Common ancestor ref (default: git merge-base branch-a branch-b)
  --project-root   Path to the git repo (default: .)
  --help           Show this help message
USAGE
  exit 2
}

BRANCH_A=""
BRANCH_B=""
BASE=""
PROJECT_ROOT="."

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch-a) BRANCH_A="$2"; shift 2 ;;
    --branch-b) BRANCH_B="$2"; shift 2 ;;
    --base) BASE="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$BRANCH_A" || -z "$BRANCH_B" ]]; then
  echo "Error: --branch-a and --branch-b are required" >&2
  usage
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': 'Project root does not exist: ' + sys.argv[1],
    'conflict': None,
    'tier': None,
    'files': [],
    'severity': None,
    'summary': None
}))
" "$PROJECT_ROOT"
  exit 2
fi

# Validate branches exist
for REF_NAME in "$BRANCH_A" "$BRANCH_B"; do
  if ! git -C "$PROJECT_ROOT" rev-parse --verify "$REF_NAME" >/dev/null 2>&1; then
    python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': 'Branch does not exist: ' + sys.argv[1],
    'conflict': None,
    'tier': None,
    'files': [],
    'severity': None,
    'summary': None
}))
" "$REF_NAME"
    exit 2
  fi
done

# Resolve base if not provided
if [[ -z "$BASE" ]]; then
  set +e
  BASE=$(git -C "$PROJECT_ROOT" merge-base -- "$BRANCH_A" "$BRANCH_B" 2>&1)
  MB_EXIT=$?
  set -e
  if [[ $MB_EXIT -ne 0 ]]; then
    python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': 'Failed to find merge-base: ' + sys.argv[1],
    'conflict': None,
    'tier': None,
    'files': [],
    'severity': None,
    'summary': None
}))
" "$BASE"
    exit 2
  fi
fi

# --- Tier 1: git merge-tree simulation ---
set +e
MERGE_OUTPUT=$(git -C "$PROJECT_ROOT" merge-tree --write-tree --name-only --no-messages -- "$BRANCH_A" "$BRANCH_B" 2>&1)
MERGE_EXIT=$?
set -e

# Exit 0: clean merge — no conflicts
if [[ $MERGE_EXIT -eq 0 ]]; then
  python3 -c "
import json
print(json.dumps({
    'status': 'success',
    'conflict': False,
    'tier': 1,
    'files': [],
    'severity': 'green',
    'summary': 'Clean merge — no textual conflicts detected'
}))
"
  exit 0
fi

# Exit != 0 and != 1: system error
if [[ $MERGE_EXIT -ne 1 ]]; then
  python3 -c "
import json, sys
print(json.dumps({
    'status': 'error',
    'error': 'git merge-tree failed (exit ' + sys.argv[1] + '): ' + sys.argv[2],
    'conflict': None,
    'tier': None,
    'files': [],
    'severity': None,
    'summary': None
}))
" "$MERGE_EXIT" "$MERGE_OUTPUT"
  exit 2
fi

# Exit 1: conflicts exist. Parse output.
# First line is tree OID, remaining lines are conflicting filenames.
TREE_OID=$(echo "$MERGE_OUTPUT" | head -1)
CONFLICT_FILES=$(echo "$MERGE_OUTPUT" | tail -n +2 | grep -v '^$' || true)

if [[ -z "$CONFLICT_FILES" ]]; then
  # merge-tree returned exit 1 but no filenames — treat as structural
  python3 -c "
import json
print(json.dumps({
    'status': 'success',
    'conflict': True,
    'tier': 1,
    'files': [],
    'severity': 'black',
    'summary': 'Structural conflict detected (no file list available)'
}))
"
  exit 1
fi

# --- Tier 2: symbol-level analysis for each conflicting file ---
# Build per-file results via python3 for reliable JSON construction
FILE_RESULTS="[]"
WORST_SEVERITY="green"

# Severity ordering for aggregation
severity_rank() {
  case "$1" in
    green)  echo 0 ;;
    yellow) echo 1 ;;
    red)    echo 2 ;;
    black)  echo 3 ;;
    *)      echo 2 ;;
  esac
}

CURRENT_WORST=0

while IFS= read -r FILE; do
  [[ -z "$FILE" ]] && continue

  # Try to get diffs for each branch against base
  set +e
  DIFF_A=$(git -C "$PROJECT_ROOT" diff "$BASE".."$BRANCH_A" -- "$FILE" 2>&1)
  DIFF_A_EXIT=$?
  DIFF_B=$(git -C "$PROJECT_ROOT" diff "$BASE".."$BRANCH_B" -- "$FILE" 2>&1)
  DIFF_B_EXIT=$?
  set -e

  # If we can't get diffs, this is a structural conflict (add/add, file/dir collision)
  if [[ $DIFF_A_EXIT -ne 0 || $DIFF_B_EXIT -ne 0 ]]; then
    FILE_RESULTS=$(python3 -c "
import json, sys
files = json.loads(sys.argv[1])
files.append({
    'path': sys.argv[2],
    'tier1_conflict': True,
    'tier2_result': 'structural',
    'symbols': []
})
print(json.dumps(files))
" "$FILE_RESULTS" "$FILE")
    CURRENT_WORST=3
    WORST_SEVERITY="black"
    continue
  fi

  # Extract symbols from each diff
  # Patterns: JS/TS function/const/class/export, Python def/class, Go func, Rust fn/struct/impl
  # Plus git @@ hunk header function annotations
  SYMBOL_PATTERN='(function|const|let|var|class|export\s+(default\s+)?(function|class|const))\s+([A-Za-z_][A-Za-z0-9_]*)|(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)|\bfunc\s+(\([^)]*\)\s+)?([A-Za-z_][A-Za-z0-9_]*)|(fn|struct|impl)\s+([A-Za-z_][A-Za-z0-9_]*)'
  HUNK_PATTERN='@@.*@@\s*(function|def|func|fn|class|impl|const|let|var|export)?\s*([A-Za-z_][A-Za-z0-9_]*)'

  # Extract from added/modified lines (lines starting with +) and hunk headers
  SYMBOLS_A=$(echo "$DIFF_A" | grep -E '^\+' | grep -oE "$SYMBOL_PATTERN" | grep -oE '[A-Za-z_][A-Za-z0-9_]*$' | sort -u || true)
  HUNK_SYMS_A=$(echo "$DIFF_A" | grep -E '^@@' | grep -oE "$HUNK_PATTERN" | grep -oE '[A-Za-z_][A-Za-z0-9_]*$' | sort -u || true)
  ALL_SYMS_A=$(printf '%s\n%s' "$SYMBOLS_A" "$HUNK_SYMS_A" | grep -v '^$' | sort -u || true)

  SYMBOLS_B=$(echo "$DIFF_B" | grep -E '^\+' | grep -oE "$SYMBOL_PATTERN" | grep -oE '[A-Za-z_][A-Za-z0-9_]*$' | sort -u || true)
  HUNK_SYMS_B=$(echo "$DIFF_B" | grep -E '^@@' | grep -oE "$HUNK_PATTERN" | grep -oE '[A-Za-z_][A-Za-z0-9_]*$' | sort -u || true)
  ALL_SYMS_B=$(printf '%s\n%s' "$SYMBOLS_B" "$HUNK_SYMS_B" | grep -v '^$' | sort -u || true)

  # Compare symbol sets
  if [[ -z "$ALL_SYMS_A" && -z "$ALL_SYMS_B" ]]; then
    # No symbols extracted — can't determine, conservative red
    TIER2_RESULT="unknown"
    FILE_SEVERITY="red"
    COMMON_SYMBOLS="[]"
  else
    COMMON=$(comm -12 <(echo "$ALL_SYMS_A") <(echo "$ALL_SYMS_B") || true)
    if [[ -n "$COMMON" ]]; then
      TIER2_RESULT="same_symbol"
      FILE_SEVERITY="red"
      COMMON_SYMBOLS=$(echo "$COMMON" | python3 -c "import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))")
    else
      TIER2_RESULT="different_symbols"
      FILE_SEVERITY="yellow"
      COMMON_SYMBOLS="[]"
    fi
  fi

  FILE_RANK=$(severity_rank "$FILE_SEVERITY")
  if [[ $FILE_RANK -gt $CURRENT_WORST ]]; then
    CURRENT_WORST=$FILE_RANK
    WORST_SEVERITY="$FILE_SEVERITY"
  fi

  FILE_RESULTS=$(python3 -c "
import json, sys
files = json.loads(sys.argv[1])
files.append({
    'path': sys.argv[2],
    'tier1_conflict': True,
    'tier2_result': sys.argv[3],
    'symbols': json.loads(sys.argv[4])
})
print(json.dumps(files))
" "$FILE_RESULTS" "$FILE" "$TIER2_RESULT" "$COMMON_SYMBOLS")

done <<< "$CONFLICT_FILES"

# Determine final conflict status: green/yellow = no blocking conflict, red/black = conflict
if [[ "$WORST_SEVERITY" == "green" || "$WORST_SEVERITY" == "yellow" ]]; then
  CONFLICT_BOOL="False"
  EXIT_CODE=0
else
  CONFLICT_BOOL="True"
  EXIT_CODE=1
fi

# Count files and build summary
python3 -c "
import json, sys

files = json.loads(sys.argv[1])
severity = sys.argv[2]
conflict = sys.argv[3] == 'True'

# Build summary
file_count = len(files)
if severity == 'green':
    summary = f'{file_count} file(s) checked — no conflicts'
elif severity == 'yellow':
    summary = f'{file_count} file(s) with textual overlap but different symbols — likely safe'
elif severity == 'red':
    red_files = [f for f in files if f['tier2_result'] in ('same_symbol', 'unknown')]
    symbols = []
    for f in red_files:
        symbols.extend(f['symbols'])
    sym_str = ', '.join(symbols) if symbols else 'unknown symbols'
    summary = f'{len(red_files)} file(s) with symbol-level conflict ({sym_str})'
else:
    summary = f'Structural conflict in {file_count} file(s)'

print(json.dumps({
    'status': 'success',
    'conflict': conflict,
    'tier': 2,
    'files': files,
    'severity': severity,
    'summary': summary
}))
" "$FILE_RESULTS" "$WORST_SEVERITY" "$CONFLICT_BOOL"

exit "$EXIT_CODE"
