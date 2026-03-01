#!/usr/bin/env bash
set -e

# archive-closed-stories.sh
# One-time migration: move all closed/done/shipped stories from epic.stories
# into the top-level archive array with a compact footprint.
#
# Usage: ./archive-closed-stories.sh <project-root>

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
EPICS_FILE="${PROJECT_ROOT}/.claude/epics.json"

if [ ! -f "$EPICS_FILE" ]; then
  echo "epics.json not found at ${EPICS_FILE}" >&2
  exit 1
fi

node - "$EPICS_FILE" <<'NODEEOF'
const fs = require('fs');
const epicsFile = process.argv[2];

const data = JSON.parse(fs.readFileSync(epicsFile, 'utf-8'));
const terminalStates = ['done', 'closed', 'shipped'];

if (!Array.isArray(data.archive)) {
  data.archive = [];
}

let archived = 0;

if (Array.isArray(data.epics)) {
  data.epics.forEach(epic => {
    if (!Array.isArray(epic.stories)) return;

    const remaining = [];
    epic.stories.forEach(story => {
      if (terminalStates.includes(story.state)) {
        data.archive.push({
          id: story.id,
          epicId: story.epicId || epic.id,
          title: story.title,
          state: story.state,
          branch: story.branch || null,
          writeFiles: story.writeFiles || []
        });
        archived++;
      } else {
        remaining.push(story);
      }
    });
    epic.stories = remaining;
  });
}

const tmpFile = epicsFile + '.tmp.' + process.pid;
fs.writeFileSync(tmpFile, JSON.stringify(data, null, 2) + '\n', 'utf8');
fs.renameSync(tmpFile, epicsFile);

process.stdout.write(`Archived ${archived} stories. epics.json updated.\n`);
NODEEOF
