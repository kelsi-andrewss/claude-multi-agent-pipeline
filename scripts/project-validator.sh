#!/bin/bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: project-validator.sh --project-root <path>

Auto-detect framework and run install → build → typecheck. Emits JSON results on stdout.

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
  echo '{"status":"fail","error":"--project-root is required"}'
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  python3 -c "import json; print(json.dumps({'status':'fail','error':'Project root does not exist: '+__import__('sys').argv[1]}))" "$PROJECT_ROOT"
  exit 1
fi

cd "$PROJECT_ROOT"

# Detect framework
FRAMEWORK="unknown"
if [[ -f "package.json" ]]; then
  FRAMEWORK="node_ts"
elif [[ -f "pyproject.toml" ]]; then
  FRAMEWORK="python"
elif [[ -f "go.mod" ]]; then
  FRAMEWORK="go"
fi

if [[ "$FRAMEWORK" == "unknown" ]]; then
  echo '{"status":"fail","framework":"unknown","error":"No recognized project type"}'
  exit 1
fi

# Temp files for capturing layer outputs
TMPDIR_LAYERS=$(mktemp -d)
trap 'rm -rf "$TMPDIR_LAYERS"' EXIT

# Run a validation layer. Writes exit code to $TMPDIR_LAYERS/<label>.exit
# and last 30 lines to $TMPDIR_LAYERS/<label>.out
run_layer() {
  local label="$1"
  local cmd="$2"
  echo "Running $label: $cmd" >&2
  set +e
  bash -c "$cmd" 2>&1 | tail -30 > "$TMPDIR_LAYERS/$label.out"
  echo "${PIPESTATUS[0]}" > "$TMPDIR_LAYERS/$label.exit"
  set -e
}

# Determine commands per framework
INSTALL_CMD=""
BUILD_CMD=""
TYPECHECK_CMD=""

if [[ "$FRAMEWORK" == "node_ts" ]]; then
  INSTALL_CMD="npm install"
  HAS_BUILD=$(python3 -c "
import json
with open('package.json') as f:
    pkg = json.load(f)
print('1' if 'build' in pkg.get('scripts', {}) else '0')
")
  if [[ "$HAS_BUILD" == "1" ]]; then
    BUILD_CMD="npm run build"
  else
    BUILD_CMD="npx tsc --noEmit"
  fi
  TYPECHECK_CMD="npx tsc --noEmit"
elif [[ "$FRAMEWORK" == "python" ]]; then
  INSTALL_CMD="pip install -e ."
elif [[ "$FRAMEWORK" == "go" ]]; then
  INSTALL_CMD="go mod download"
  BUILD_CMD="go build ./..."
  TYPECHECK_CMD="go vet ./..."
fi

# Run layers sequentially — all run regardless of prior failures
if [[ -n "$INSTALL_CMD" ]]; then run_layer "install" "$INSTALL_CMD"; fi
if [[ -n "$BUILD_CMD" ]]; then run_layer "build" "$BUILD_CMD"; fi
if [[ -n "$TYPECHECK_CMD" ]]; then run_layer "typecheck" "$TYPECHECK_CMD"; fi

# Emit JSON via python for safe escaping
python3 - "$FRAMEWORK" "$TMPDIR_LAYERS" "$INSTALL_CMD" "$BUILD_CMD" "$TYPECHECK_CMD" <<'PYEOF'
import json, sys, os

framework = sys.argv[1]
tmpdir = sys.argv[2]
cmds = {"install": sys.argv[3], "build": sys.argv[4], "typecheck": sys.argv[5]}

layers = {}
overall = "pass"

for name in ("install", "build", "typecheck"):
    if not cmds[name]:
        layers[name] = {"status": "skip", "output": ""}
        continue
    exit_file = os.path.join(tmpdir, f"{name}.exit")
    out_file = os.path.join(tmpdir, f"{name}.out")
    exit_code = int(open(exit_file).read().strip()) if os.path.exists(exit_file) else 1
    output = open(out_file).read() if os.path.exists(out_file) else ""
    status = "pass" if exit_code == 0 else "fail"
    if status == "fail":
        overall = "fail"
    layers[name] = {"status": status, "output": output[:2000]}

result = {"status": overall, "framework": framework, "layers": layers}
print(json.dumps(result))
PYEOF
