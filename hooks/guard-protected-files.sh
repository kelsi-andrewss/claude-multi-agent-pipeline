#!/bin/bash
# PreToolUse hook for Edit and Write.
# Blocks edits to protected Konva files unless explicit per-session permission
# has been granted via a $CLAUDE_TEMP_DIR sentinel file.
#
# Protected files:
#   BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx
#
# Permission signal: $CLAUDE_TEMP_DIR/konva-permission-<basename>
# Grant permission: main session writes that file when user says "I grant permission to edit X"
#
# Exit 0 = allow
# Exit 2 = block

source "$(dirname "$0")/lib/profile.sh"
require_profile 2

# Fast path: if inside a worktree, the worktree-level guard handles scope.
# This hook runs at the main session level to catch main-session attempts.
if [[ "$PWD" == */\.claude/worktrees/* ]]; then
  cat > /dev/null
  exit 0
fi

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 "$HOME/.claude/hooks/lib/parse_hook_input.py" file_path)

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
PERMISSION_FILE="$CLAUDE_TEMP_DIR/konva-permission-${PROTECTED_NAME}"

if [[ -f "$PERMISSION_FILE" ]]; then
  # Permission granted for this session
  exit 0
fi

# Block — no permission
echo "BLOCKED: $PROTECTED_NAME is a protected Konva file." >&2
echo "Grant explicit permission first by saying: \"I grant permission to edit $PROTECTED_NAME\"" >&2
echo "This causes the main session to write: $CLAUDE_TEMP_DIR/konva-permission-${PROTECTED_NAME}" >&2
exit 2
