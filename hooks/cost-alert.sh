#!/bin/bash
# Stop hook: cost alert.
# Reads today's estimated cost from the claude-code-tracker tokens.json.
# If cost exceeds the configured threshold, prints a warning to stderr.
# Exit 0 always (advisory only).

CONFIG_FILE="/Users/kelsiandrews/.claude/hooks/cost-alert-config.json"
TRACKER_DIR="/opt/homebrew/opt/claude-code-tracker/libexec/src"

# Read threshold from config
THRESHOLD=$(python3 -c "
import json, sys
try:
    with open('$CONFIG_FILE') as f:
        print(f.read().strip())
except:
    print('{\"threshold_usd\": 5.00}')
" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('threshold_usd', 5.00))
" 2>/dev/null)

THRESHOLD="${THRESHOLD:-5.00}"

# Find today's tokens.json — tracker writes to a date-stamped file
TODAY=$(date +%Y-%m-%d)
TOKENS_FILE=$(find "$HOME/.claude-tracker" "$HOME/.config/claude-tracker" /tmp 2>/dev/null \
  -name "tokens-${TODAY}.json" -o -name "tokens.json" 2>/dev/null | head -1)

if [[ -z "$TOKENS_FILE" || ! -f "$TOKENS_FILE" ]]; then
  # Tracker file not found — skip silently
  exit 0
fi

COST=$(python3 -c "
import json, sys
try:
    with open('$TOKENS_FILE') as f:
        d = json.load(f)
    # Support both flat and nested structures
    cost = d.get('estimated_cost_usd') or d.get('today', {}).get('estimated_cost_usd') or 0
    print(f'{float(cost):.2f}')
except:
    print('0.00')
" 2>/dev/null)

COST="${COST:-0.00}"

# Compare: if cost >= threshold, warn
EXCEEDED=$(python3 -c "
cost = float('$COST')
threshold = float('$THRESHOLD')
print('yes' if cost >= threshold else 'no')
" 2>/dev/null)

if [[ "$EXCEEDED" == "yes" ]]; then
  echo "" >&2
  echo "[cost-alert] Today: \$$COST / threshold: \$$THRESHOLD — consider reviewing usage" >&2
fi

exit 0
