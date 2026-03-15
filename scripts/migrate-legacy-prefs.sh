#!/usr/bin/env bash
# migrate-legacy-prefs.sh — One-time migration of behavioral-prefs.md to correction_groups DB
# Idempotent: skips entries whose theme already exists in the DB

set -euo pipefail

PREFS_FILE="$HOME/.claude/behavioral-prefs.md"
DB_FILE="$HOME/.claude/.claude/epics.db"

if [[ ! -f "$PREFS_FILE" ]]; then
  echo "No behavioral-prefs.md found — nothing to migrate."
  exit 0
fi

if [[ ! -f "$DB_FILE" ]]; then
  echo "ERROR: epics.db not found at $DB_FILE"
  exit 1
fi

# Verify source and text columns exist (added by story-713)
HAS_SOURCE=$(sqlite3 "$DB_FILE" "PRAGMA table_info(correction_groups);" | grep -c "source" || true)
HAS_TEXT=$(sqlite3 "$DB_FILE" "PRAGMA table_info(correction_groups);" | grep -c "^[0-9]*|text|" || true)
if [[ "$HAS_SOURCE" -eq 0 || "$HAS_TEXT" -eq 0 ]]; then
  echo "ERROR: correction_groups missing source/text columns. Run story-713 schema migration first."
  exit 1
fi

NOW=$(date +%s)
MIGRATED=0
SKIPPED=0
CURRENT_HEADING=""

while IFS= read -r line; do
  # Track current heading for theme derivation
  if [[ "$line" =~ ^##[[:space:]]+(.*) ]]; then
    CURRENT_HEADING="${BASH_REMATCH[1]}"
    continue
  fi

  # Skip non-preference lines (blank, metadata comment, header, intro paragraph)
  [[ -z "$line" ]] && continue
  [[ "$line" =~ ^# ]] && continue
  [[ "$line" =~ ^\<\!-- ]] && continue
  [[ ! "$line" =~ ^-[[:space:]] ]] && continue

  # Extract preference text (strip leading "- ")
  PREF_TEXT="${line#- }"

  # Derive theme slug from heading (lowercase, spaces to hyphens, truncate)
  THEME=$(echo "$CURRENT_HEADING" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9 ]//g' | tr ' ' '-' | cut -c1-60)
  # If multiple bullets under same heading, append a hash suffix for uniqueness
  THEME_CHECK=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM correction_groups WHERE theme='$THEME' AND source='manual';")
  if [[ "$THEME_CHECK" -gt 0 ]]; then
    # Append short hash of pref text for uniqueness
    HASH=$(echo "$PREF_TEXT" | md5sum | cut -c1-6 2>/dev/null || echo "$PREF_TEXT" | md5 | cut -c1-6)
    THEME="${THEME}-${HASH}"
  fi

  # Check if this exact theme already exists (idempotent)
  EXISTS=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM correction_groups WHERE theme='$(echo "$THEME" | sed "s/'/''/g")';")
  if [[ "$EXISTS" -gt 0 ]]; then
    ((SKIPPED++))
    continue
  fi

  # Insert into correction_groups
  sqlite3 "$DB_FILE" "INSERT INTO correction_groups (theme, status, count, correction_dates, source, text, created_at, updated_at) VALUES ('$(echo "$THEME" | sed "s/'/''/g")', 'promoted', NULL, '[]', 'manual', '$(echo "$PREF_TEXT" | sed "s/'/''/g")', $NOW, $NOW);"
  ((MIGRATED++))
done < "$PREFS_FILE"

echo "Migration complete: $MIGRATED entries inserted, $SKIPPED skipped (already exist)."

# Verify migration
TOTAL=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM correction_groups WHERE source='manual';")
echo "Total manual entries in DB: $TOTAL"

# Delete the file
rm "$PREFS_FILE"
echo "Deleted behavioral-prefs.md"
