#!/bin/bash
# PreToolUse hook for Write and Edit.
# Appends an entry to skill-changelog.md when a skill SKILL.md file is created or modified.
# Always exits 0 (never blocks the write).

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
path = d.get('tool_input', {}).get('file_path', '')
if not path:
    path = d.get('tool_input', {}).get('path', '')
print(path)
" 2>/dev/null)

# Only care about skills/*/SKILL.md
if [[ ! "$FILE_PATH" == */skills/*/SKILL.md ]]; then
  exit 0
fi

# Extract skill name from path
SKILL_NAME=$(echo "$FILE_PATH" | sed -n 's|.*/skills/\([^/]*\)/SKILL.md|\1|p')
if [[ -z "$SKILL_NAME" ]]; then
  exit 0
fi

CHANGELOG="$HOME/.claude/skill-changelog.md"
TODAY=$(date +%Y-%m-%d)

# Determine action: created vs modified
if [[ -f "$FILE_PATH" ]]; then
  ACTION="modified"
else
  ACTION="created"
fi

# Extract description from existing file (for modified) or skip (for created, file doesn't exist yet)
DESC="updated"
if [[ "$ACTION" == "modified" ]] && [[ -f "$FILE_PATH" ]]; then
  DESC=$(python3 -c "
import sys
desc_lines = []
in_desc = False
with open('$FILE_PATH') as f:
    for line in f:
        if line.startswith('description:'):
            rest = line[len('description:'):].strip()
            if rest and rest != '>':
                print(rest.strip('\"').strip(\"'\"))
                sys.exit(0)
            in_desc = True
            continue
        if in_desc:
            if line.startswith('  ') or line.startswith('\t'):
                desc_lines.append(line.strip())
            else:
                break
if desc_lines:
    print(' '.join(desc_lines)[:80])
else:
    print('updated')
" 2>/dev/null)
fi

# Append entry
echo "- ${TODAY} ${ACTION} /${SKILL_NAME} — ${DESC}" >> "$CHANGELOG"

exit 0
