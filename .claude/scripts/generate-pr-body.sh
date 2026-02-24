#!/usr/bin/env bash
# generate-pr-body.sh — Generate structured PR description from epics.json and git state
# Usage: generate-pr-body.sh <repo-root> <epic-branch>
#
# Reads story titles and plan descriptions from epics.json for the epic,
# generates PR body with sections: "## Stories merged", "## Files changed", and git log.
# Prints the body to stdout. Robust to missing fields.
set -euo pipefail

REPO_ROOT="$1"
EPIC_BRANCH="$2"

# Extract epic slug from branch name (e.g. epic/my-feature -> my-feature)
EPIC_SLUG="${EPIC_BRANCH#epic/}"

EPICS_JSON="${REPO_ROOT}/epics.json"

# Generate stories section using python3
python3 << PYTHON_EOF
import json
import sys

repo_root = '$REPO_ROOT'
epic_slug = '$EPIC_SLUG'

try:
    with open(f'{repo_root}/epics.json', 'r') as f:
        data = json.load(f)
except Exception:
    print('## Stories merged')
    sys.exit(0)

# Find the epic by branch name
epic = None
for e in data.get('epics', []):
    branch = e.get('branch', '')
    if branch == f'epic/{epic_slug}':
        epic = e
        break

if not epic:
    print('## Stories merged')
    sys.exit(0)

# Build stories list (only closed stories)
print('## Stories merged')
for story in epic.get('stories', []):
    if story.get('state') == 'closed':
        title = story.get('title', '')
        story_id = story.get('id', '')
        if title:
            print(f'- {title} ({story_id})')
        elif story_id:
            print(f'- {story_id}')
PYTHON_EOF

# Generate files changed section
echo ""
echo "## Files changed"
git -C "$REPO_ROOT" diff --stat "origin/main" "${EPIC_BRANCH}" 2>/dev/null || \
  git -C "$REPO_ROOT" diff --stat "main" "${EPIC_BRANCH}" 2>/dev/null || \
  echo "(no changes)"

# Generate git log summary
echo ""
echo "## Commits"
git -C "$REPO_ROOT" log --oneline "origin/main..${EPIC_BRANCH}" 2>/dev/null || \
  git -C "$REPO_ROOT" log --oneline "main..${EPIC_BRANCH}" 2>/dev/null || \
  echo "(no commits)"
