#!/usr/bin/env bash
# update-epics.sh — Atomic epics.json patch applier (ORCHESTRATION.md §15.1)
# Usage: update-epics.sh <project-root> '<json-patch>'
#
# Patch formats:
#   {"storyId":"story-053","fields":{"state":"running","branch":"story/foo"}}
#   {"storyId":"story-053","fields":{"state":"closed"}}
#   {"epicId":"epic-007","fields":{"prNumber":99}}
#   {"newStory":{...full story object...},"epicId":"epic-007"}
#
# Exits 0 on success, non-zero with error message on failure.
set -euo pipefail

PROJECT_ROOT="$1"
JSON_PATCH="$2"
EPICS_FILE="${PROJECT_ROOT}/.claude/epics.json"

if [ ! -f "$EPICS_FILE" ]; then
  echo "ERROR: epics.json not found at ${EPICS_FILE}" >&2
  exit 1
fi

TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

python3 - "$EPICS_FILE" "$JSON_PATCH" "$TMPFILE" <<'PYEOF'
import json, sys

epics_path = sys.argv[1]
patch_str  = sys.argv[2]
tmp_path   = sys.argv[3]

with open(epics_path, 'r') as f:
    data = json.load(f)

patch = json.loads(patch_str)

if 'newStory' in patch:
    epic_id = patch['epicId']
    new_story = patch['newStory']
    for epic in data['epics']:
        if epic['id'] == epic_id:
            epic.setdefault('stories', []).append(new_story)
            break
    else:
        print(f"ERROR: epic {epic_id} not found", file=sys.stderr)
        sys.exit(1)

elif 'storyId' in patch:
    story_id = patch['storyId']
    fields   = patch['fields']
    found = False
    for epic in data['epics']:
        for story in epic.get('stories', []):
            if story['id'] == story_id:
                story.update(fields)
                found = True
                break
        if found:
            break
    if not found:
        print(f"ERROR: story {story_id} not found", file=sys.stderr)
        sys.exit(1)

elif 'epicId' in patch:
    epic_id = patch['epicId']
    fields  = patch['fields']
    for epic in data['epics']:
        if epic['id'] == epic_id:
            epic.update(fields)
            break
    else:
        print(f"ERROR: epic {epic_id} not found", file=sys.stderr)
        sys.exit(1)

else:
    print("ERROR: patch must contain storyId, epicId, or newStory", file=sys.stderr)
    sys.exit(1)

def validate(data):
    VALID_STATES = {'filling', 'queued', 'running', 'testing', 'reviewing', 'merging', 'closed', 'blocked'}
    REQUIRED_STORY_FIELDS = {'id', 'epicId', 'title', 'state', 'branch', 'writeFiles', 'needsTesting', 'needsReview'}
    epic_ids = {e['id'] for e in data['epics']}
    story_ids = []
    errors = []
    for epic in data['epics']:
        for story in epic.get('stories', []):
            # check required fields
            missing = REQUIRED_STORY_FIELDS - set(story.keys())
            if missing:
                errors.append(f"story {story.get('id','?')} missing fields: {missing}")
            # check valid state
            if story.get('state') not in VALID_STATES:
                errors.append(f"story {story.get('id','?')} has invalid state: {story.get('state')}")
            # check epicId exists
            if story.get('epicId') not in epic_ids:
                errors.append(f"story {story.get('id','?')} references non-existent epicId: {story.get('epicId')}")
            # check duplicate IDs
            sid = story.get('id')
            if sid in story_ids:
                errors.append(f"duplicate story id: {sid}")
            else:
                story_ids.append(sid)
    return errors

with open(tmp_path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')

errors = validate(data)
if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
PYEOF

mv "$TMPFILE" "$EPICS_FILE"
echo "update-epics OK: ${JSON_PATCH}"
