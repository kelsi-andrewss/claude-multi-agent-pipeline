#!/bin/bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: wiring-checklist.sh --project-root <path>

Run 8 deterministic grep-based checks for UI wiring patterns. Emits JSON on stdout.

Arguments:
  --project-root   Absolute path to the project root (required)
  --help           Show this help message
USAGE
  exit 2
}

PROJECT_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo '{"status":"fail","error":"--project-root is required","score":"0/8","checks":[]}'
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  python3 -c "import json; print(json.dumps({'status':'fail','error':'Project root does not exist: '+__import__('sys').argv[1],'score':'0/8','checks':[]}))" "$PROJECT_ROOT"
  exit 1
fi

cd "$PROJECT_ROOT"

# Collect all source files (exclude node_modules, .next, dist, build)
FIND_ARGS=( -type f \( -name "*.tsx" -o -name "*.ts" -o -name "*.jsx" -o -name "*.js" \) \
  ! -path "*/node_modules/*" ! -path "*/.next/*" ! -path "*/dist/*" ! -path "*/build/*" )

# Create a temp file with all source concatenated for single-file grep checks
TMPDIR_WIRING=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WIRING"' EXIT

SRC_CONCAT="$TMPDIR_WIRING/all_src.txt"
FILE_LIST="$TMPDIR_WIRING/files.txt"

find . "${FIND_ARGS[@]}" > "$FILE_LIST" 2>/dev/null || true

if [[ ! -s "$FILE_LIST" ]]; then
  echo '{"status":"fail","error":"No source files found","score":"0/8","checks":[]}'
  exit 1
fi

# Concatenate all source for pattern matching
xargs cat < "$FILE_LIST" > "$SRC_CONCAT" 2>/dev/null || true

# Check 1: event_binding — onChange/onSubmit/onClick followed by a function ref
c1=$(grep -cE 'on(Change|Submit|Click)=\{[a-zA-Z]' "$SRC_CONCAT" 2>/dev/null || echo 0)

# Check 2: fetch_to_state — files containing both fetch( and set[A-Z]
c2=0
while IFS= read -r f; do
  has_fetch=$(grep -l 'fetch(' "$f" 2>/dev/null || true)
  has_set=$(grep -lE 'set[A-Z]' "$f" 2>/dev/null || true)
  if [[ -n "$has_fetch" && -n "$has_set" ]]; then
    c2=$((c2 + 1))
  fi
done < "$FILE_LIST"

# Check 3: click_to_state — files with both onClick and set[A-Z]
c3=0
while IFS= read -r f; do
  has_click=$(grep -l 'onClick' "$f" 2>/dev/null || true)
  has_set=$(grep -lE 'set[A-Z]' "$f" 2>/dev/null || true)
  if [[ -n "$has_click" && -n "$has_set" ]]; then
    c3=$((c3 + 1))
  fi
done < "$FILE_LIST"

# Check 4: conditional_render — JSX ternary or && rendering
c4=$(grep -cE '\{.*&&.*<|\{.*\?.*<.*:' "$SRC_CONCAT" 2>/dev/null || echo 0)

# Check 5: shared_state — useContext/createContext in 2+ files, or custom hook imported in 2+ files
c5_context=0
while IFS= read -r f; do
  if grep -qE 'useContext|createContext' "$f" 2>/dev/null; then
    c5_context=$((c5_context + 1))
  fi
done < "$FILE_LIST"
c5=$c5_context

# Check 6: toggle_pattern — set[A-Z]...(!  or set[A-Z]...prev or toggle
c6=$(grep -cE 'set[A-Z].*\(!|set[A-Z].*prev|toggle' "$SRC_CONCAT" 2>/dev/null || echo 0)

# Check 7: modal_close — onClose or setShow.*false or setOpen.*false or setSelected.*null
c7=$(grep -cE 'onClose|set(Show|Open|Visible).*false|set(Selected|Active).*null' "$SRC_CONCAT" 2>/dev/null || echo 0)

# Check 8: key_handler — onKeyDown/onKeyUp/addEventListener.*key
c8=$(grep -cE 'onKeyDown|onKeyUp|addEventListener.*key' "$SRC_CONCAT" 2>/dev/null || echo 0)

# Emit JSON via python
python3 - "$c1" "$c2" "$c3" "$c4" "$c5" "$c6" "$c7" "$c8" <<'PYEOF'
import json, sys

names = [
    "event_binding",
    "fetch_to_state",
    "click_to_state",
    "conditional_render",
    "shared_state",
    "toggle_pattern",
    "modal_close",
    "key_handler"
]

counts = [int(sys.argv[i+1]) for i in range(8)]
# shared_state passes if 2+ files have context usage
thresholds = [1, 1, 1, 1, 2, 1, 1, 1]

checks = []
score = 0
for i, name in enumerate(names):
    passed = counts[i] >= thresholds[i]
    if passed:
        score += 1
    checks.append({
        "name": name,
        "status": "pass" if passed else "fail",
        "matches": counts[i]
    })

overall = "pass" if score >= 6 else "fail"
result = {
    "status": overall,
    "score": f"{score}/8",
    "checks": checks
}
print(json.dumps(result))
PYEOF
