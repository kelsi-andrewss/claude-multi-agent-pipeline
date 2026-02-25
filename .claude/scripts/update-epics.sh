#!/usr/bin/env bash
set -e

# update-epics.sh
# Args: <project-root> '<json-patch>'
#
# Supported patch shapes:
#   {"storyId":"story-053","fields":{"state":"running","branch":"story/foo"}}
#   {"epicId":"epic-007","fields":{"prNumber":99}}
#   {"newStory":{...full story object...},"epicId":"epic-007"}

PROJECT_ROOT="$1"
JSON_PATCH="$2"

if [ -z "$PROJECT_ROOT" ] || [ -z "$JSON_PATCH" ]; then
  echo "Usage: update-epics.sh <project-root> '<json-patch>'" >&2
  exit 1
fi

EPICS_FILE="${PROJECT_ROOT}/.claude/epics.json"

if [ ! -f "$EPICS_FILE" ]; then
  echo "epics.json not found at ${EPICS_FILE}" >&2
  exit 1
fi

node - "$EPICS_FILE" "$JSON_PATCH" <<'NODEEOF'
const fs = require('fs');
const path = require('path');

const epicsFile = process.argv[1];
const patch = JSON.parse(process.argv[2]);

const data = JSON.parse(fs.readFileSync(epicsFile, 'utf8'));

if (patch.newStory && patch.epicId) {
  // Add a new story to the given epic's stories array
  const epicId = patch.epicId;
  const newStory = patch.newStory;

  // Find the epic
  const epic = data.epics ? data.epics.find(e => e.id === epicId) : null;

  if (data.epics && epic) {
    // epics.json structure: { epics: [ { id, title, ..., stories: [...] } ] }
    if (!Array.isArray(epic.stories)) {
      epic.stories = [];
    }
    epic.stories.push(newStory);
  } else if (Array.isArray(data)) {
    // Flat array structure: top-level is array of epics
    const epicEntry = data.find(e => e.id === epicId);
    if (!epicEntry) {
      process.stderr.write(`Epic ${epicId} not found\n`);
      process.exit(1);
    }
    if (!Array.isArray(epicEntry.stories)) {
      epicEntry.stories = [];
    }
    epicEntry.stories.push(newStory);
  } else {
    // Structure: { epics: [...], stories: [...] } (flat stories list)
    if (!Array.isArray(data.stories)) {
      data.stories = [];
    }
    data.stories.push(newStory);
  }

} else if (patch.storyId && patch.fields) {
  // Update fields on an existing story
  let found = false;

  const updateStory = (story) => {
    if (story.id === patch.storyId) {
      Object.assign(story, patch.fields);
      found = true;
    }
  };

  if (data.epics) {
    data.epics.forEach(epic => {
      if (Array.isArray(epic.stories)) epic.stories.forEach(updateStory);
    });
  }
  if (Array.isArray(data.stories)) {
    data.stories.forEach(updateStory);
  }
  if (Array.isArray(data)) {
    data.forEach(epic => {
      if (Array.isArray(epic.stories)) epic.stories.forEach(updateStory);
    });
  }

  if (!found) {
    process.stderr.write(`Story ${patch.storyId} not found\n`);
    process.exit(1);
  }

} else if (patch.epicId && patch.fields) {
  // Update fields on an existing epic
  let found = false;

  const updateEpic = (epic) => {
    if (epic.id === patch.epicId) {
      Object.assign(epic, patch.fields);
      found = true;
    }
  };

  if (Array.isArray(data.epics)) {
    data.epics.forEach(updateEpic);
  }
  if (Array.isArray(data)) {
    data.forEach(updateEpic);
  }

  if (!found) {
    process.stderr.write(`Epic ${patch.epicId} not found\n`);
    process.exit(1);
  }

} else {
  process.stderr.write('Unrecognized patch shape. Expected newStory+epicId, storyId+fields, or epicId+fields.\n');
  process.exit(1);
}

// Write back atomically via temp file + rename
const tmpFile = epicsFile + '.tmp.' + process.pid;
fs.writeFileSync(tmpFile, JSON.stringify(data, null, 2) + '\n', 'utf8');
fs.renameSync(tmpFile, epicsFile);

process.stdout.write('epics.json updated\n');
NODEEOF

exit 0
