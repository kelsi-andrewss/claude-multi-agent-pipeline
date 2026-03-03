#!/bin/bash
# Stop hook — session learning check.
# Detects if disagreements or outcomes were modified this session.
# Silent when nothing changed. Only outputs actionable findings.

SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
SNAPSHOT="/tmp/session-mtimes-${SESSION_ID}"

if [[ ! -f "$SNAPSHOT" ]]; then
  exit 0
fi

source "$SNAPSHOT"

if stat -f %m / >/dev/null 2>&1; then
  mtime() { stat -f %m "$1" 2>/dev/null || echo "0"; }
elif stat -c %Y / >/dev/null 2>&1; then
  mtime() { stat -c %Y "$1" 2>/dev/null || echo "0"; }
else
  mtime() { python3 -c "import os; print(int(os.path.getmtime('$1')))" 2>/dev/null || echo "0"; }
fi

CURRENT_DISAGREE=$(mtime "$HOME/.claude/disagreements.md")
CURRENT_OUTCOMES=$(mtime "$HOME/.claude/outcomes.md")

DISAGREE_CHANGED=false
OUTCOMES_CHANGED=false
[[ "$CURRENT_DISAGREE" != "$DISAGREE_MTIME" ]] && DISAGREE_CHANGED=true
[[ "$CURRENT_OUTCOMES" != "$OUTCOMES_MTIME" ]] && OUTCOMES_CHANGED=true

if [[ "$DISAGREE_CHANGED" == true && "$OUTCOMES_CHANGED" == false ]]; then
  echo "disagreements.md modified — outcomes.md unchanged"
  echo "→ Log an outcome for this session's disagreement(s) next session."
elif [[ "$DISAGREE_CHANGED" == true && "$OUTCOMES_CHANGED" == true ]]; then
  echo "disagreements.md + outcomes.md both updated"
  echo "→ Distillation will trigger at threshold."
elif [[ "$OUTCOMES_CHANGED" == true ]]; then
  echo "outcomes.md updated → distillation will trigger at threshold."
fi

rm -f "$SNAPSHOT"
exit 0
