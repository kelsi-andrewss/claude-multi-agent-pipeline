#!/bin/bash
# Stop hook: cost alert.
# Reads today's estimated cost from the claude-code-tracker tokens.json.
# If cost exceeds the configured threshold, prints a warning to stderr.
# Exit 0 always (advisory only).

source "$(dirname "$0")/lib/profile.sh"
require_profile 1

CLAUDE_ROOT="$(git -C "$(dirname "$(realpath "$0")")" rev-parse --show-toplevel)"
CONFIG_FILE="${CLAUDE_ROOT}/hooks/cost-alert-config.json"

# Read threshold from config
THRESHOLD=$(python3 - "$CONFIG_FILE" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.loads(f.read().strip())
    print(d.get('threshold_usd', 5.00))
except Exception:
    print('5.00')
PYEOF
)

THRESHOLD="${THRESHOLD:-5.00}"

# Find today's tokens.json — tracker writes to a date-stamped file
TODAY=$(date +%Y-%m-%d)
TOKENS_FILE=$(find "$HOME/.claude-tracker" "$HOME/.config/claude-tracker" /tmp 2>/dev/null \
  -name "tokens-${TODAY}.json" -o -name "tokens.json" 2>/dev/null | head -1)

if [[ -z "$TOKENS_FILE" || ! -f "$TOKENS_FILE" ]]; then
  # Tracker file not found — skip silently
  exit 0
fi

COST=$(python3 - "$TOKENS_FILE" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    cost = d.get('estimated_cost_usd') or d.get('today', {}).get('estimated_cost_usd') or 0
    print(f'{float(cost):.2f}')
except Exception:
    print('0.00')
PYEOF
)

COST="${COST:-0.00}"

# Compare: if cost >= threshold, warn
EXCEEDED=$(python3 - "$COST" "$THRESHOLD" <<'PYEOF'
import sys
cost = float(sys.argv[1])
threshold = float(sys.argv[2])
print('yes' if cost >= threshold else 'no')
PYEOF
)

if [[ "$EXCEEDED" == "yes" ]]; then
  echo "" >&2
  echo "[cost-alert] Today: \$$COST / threshold: \$$THRESHOLD — consider reviewing usage" >&2
  bash "$HOME/.claude/scripts/emit-event.sh" "hook.cost-alert" "hook" "cost-threshold" "{\"cost_usd\":\"$COST\",\"threshold_usd\":\"$THRESHOLD\",\"result\":\"warned\"}" || true
fi

exit 0
