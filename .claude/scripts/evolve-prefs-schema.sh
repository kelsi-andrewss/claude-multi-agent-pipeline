#!/bin/bash
# Idempotent schema migration: add source and text columns to correction_groups.
# Usage: evolve-prefs-schema.sh [db_path]

DB="${1:-$HOME/.claude/.claude/epics.db}"

if [[ ! -f "$DB" ]]; then
  exit 0
fi

# Check if correction_groups table exists
HAS_TABLE=$(sqlite3 "$DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='correction_groups';" 2>/dev/null)
if [[ "$HAS_TABLE" != "1" ]]; then
  exit 0
fi

# Add source column if missing
HAS_SOURCE=$(sqlite3 "$DB" "PRAGMA table_info(correction_groups);" 2>/dev/null | grep -c '|source|')
if [[ "$HAS_SOURCE" -eq 0 ]]; then
  sqlite3 "$DB" "ALTER TABLE correction_groups ADD COLUMN source TEXT DEFAULT 'auto';" || exit 1
fi

# Add text column if missing
HAS_TEXT=$(sqlite3 "$DB" "PRAGMA table_info(correction_groups);" 2>/dev/null | grep -c '|text|')
if [[ "$HAS_TEXT" -eq 0 ]]; then
  sqlite3 "$DB" "ALTER TABLE correction_groups ADD COLUMN text TEXT DEFAULT '';" || exit 1
fi

exit 0
