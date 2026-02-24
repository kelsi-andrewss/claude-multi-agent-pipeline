#!/bin/bash
# PreToolUse hook for Edit and Write.
# Blocks edits to protected Konva files unless explicit per-session permission
# has been granted via a /tmp sentinel file.
#
# Protected files:
#   BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx
#
# Permission signal: /tmp/konva-permission-<SESSION_ID>-<basename>
# Grant permission: main session writes that file when user says "I grant permission to edit X"
#
# Exit 0 = allow
# Exit 2 = block

# Fast path: if inside a worktree, the worktree-level guard handles scope.
# This hook runs at the main session level to catch main-session attempts.
if [[ "$PWD" == */\.claude/worktrees/* ]]; then
  cat > /dev/null
  exit 0
fi

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
path = d.get('tool_input', {}).get('file_path', '')
if not path:
    path = d.get('tool_input', {}).get('path', '')
print(path)
" 2>/dev/null)

# Protected Konva file basenames
PROTECTED_FILES=("BoardCanvas.jsx" "StickyNote.jsx" "Frame.jsx" "Shape.jsx" "LineShape.jsx" "Cursors.jsx")

# Check if the file being edited is a protected file
BASENAME=$(basename "$FILE_PATH")
IS_PROTECTED=0
for pf in "${PROTECTED_FILES[@]}"; do
  if [[ "$BASENAME" == "$pf" ]]; then
    IS_PROTECTED=1
    PROTECTED_NAME="$pf"
    break
  fi
done

if [[ "$IS_PROTECTED" == "0" ]]; then
  exit 0
fi

# Check for permission sentinel file
SESSION_ID="${PPID:-$$}"
PERMISSION_FILE="/tmp/konva-permission-${SESSION_ID}-${PROTECTED_NAME}"

if [[ -f "$PERMISSION_FILE" ]]; then
  # Permission granted for this session
  exit 0
fi

# Block — no permission
echo "BLOCKED: $PROTECTED_NAME is a protected Konva file." >&2
echo "Grant explicit permission first by saying: \"I grant permission to edit $PROTECTED_NAME\"" >&2
echo "This causes the main session to write: /tmp/konva-permission-${SESSION_ID}-${PROTECTED_NAME}" >&2
exit 2
