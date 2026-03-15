#!/usr/bin/env bash
set -e

# archive-closed-stories.sh
# Marks all done/shipped stories as archived in epics.db.
#
# Usage: ./archive-closed-stories.sh [project-root]

PROJECT_ROOT="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
DB_FILE="${PROJECT_ROOT}/.claude/epics.db"

if [ ! -f "$DB_FILE" ]; then
  echo "epics.db not found at ${DB_FILE}" >&2
  exit 1
fi

ARCHIVED=$(sqlite3 "$DB_FILE" "
  UPDATE stories SET archived=1 WHERE state IN ('done','shipped') AND archived=0;
  SELECT changes();
")

echo "Archived ${ARCHIVED} stories. epics.db updated."
