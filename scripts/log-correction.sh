#!/bin/bash
# Log a correction directly to the correction_groups table in epics.db.
# Replaces the old corrections.md append workflow.
#
# Usage: scripts/log-correction.sh "theme text" [YYYY-MM-DD]
#
# Arguments:
#   $1 - Theme text (required). Description of the correction.
#   $2 - ISO date (optional). Defaults to today.
#
# Output: JSON to stdout with group_id, count, and whether it was new.
# Exit 0 on success, exit 1 on error.

set -euo pipefail

THEME="${1:-}"
if [[ -z "$THEME" ]]; then
  echo "Usage: scripts/log-correction.sh \"theme text\" [YYYY-MM-DD]" >&2
  exit 1
fi

if [[ ${#THEME} -lt 20 ]]; then
  echo '{"status":"skipped","reason":"theme too short (min 20 chars)"}'
  exit 0
fi

if echo "$THEME" | grep -qi "not a correction"; then
  echo '{"status":"skipped","reason":"contains not-a-correction marker"}'
  exit 0
fi

DATE="${2:-$(date +%Y-%m-%d)}"
DB_FILE="$HOME/.claude/.claude/epics.db"

if [[ ! -f "$DB_FILE" ]]; then
  echo "Error: epics.db not found at $DB_FILE" >&2
  exit 1
fi

python3 - "$DB_FILE" "$THEME" "$DATE" <<'PYEOF'
import json, sqlite3, sys, time

db_file = sys.argv[1]
theme = sys.argv[2]
date = sys.argv[3]

conn = sqlite3.connect(db_file, timeout=5)
cursor = conn.cursor()

cursor.execute(
    "CREATE TABLE IF NOT EXISTS correction_groups ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "theme TEXT NOT NULL, "
    "status TEXT DEFAULT 'accumulating' CHECK(status IN ('accumulating','pending_promotion','promoted','dismissed')), "
    "count INTEGER DEFAULT 1, "
    "correction_dates TEXT DEFAULT '[]', "
    "embedding BLOB, "
    "promoted_at TEXT, "
    "created_at INTEGER, "
    "updated_at INTEGER, "
    "source TEXT DEFAULT 'auto', "
    "text TEXT DEFAULT '')"
)
cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_correction_groups_status ON correction_groups(status)"
)

row = cursor.execute(
    "SELECT id, count, correction_dates, status FROM correction_groups "
    "WHERE theme = ? LIMIT 1",
    (theme,)
).fetchone()

now = int(time.time())

if row:
    group_id, old_count, old_dates_str, old_status = row

    if old_status in ('promoted', 'dismissed'):
        print(json.dumps({"status": "ok", "group_id": group_id, "count": old_count, "new": False, "note": f"already {old_status}"}))
        conn.close()
        sys.exit(0)

    new_count = old_count + 1
    old_dates = json.loads(old_dates_str) if old_dates_str else []
    old_dates.append(date)
    new_status = 'pending_promotion' if new_count >= 3 else old_status  # Must match PROMOTION_THRESHOLD in hooks/lib/signal_processor.py

    cursor.execute(
        "UPDATE correction_groups SET count=?, correction_dates=?, status=?, updated_at=? WHERE id=?",
        (new_count, json.dumps(old_dates), new_status, now, group_id)
    )
    conn.commit()
    conn.close()
    print(json.dumps({"status": "ok", "group_id": group_id, "count": new_count, "new": False}))
else:
    cursor.execute(
        "INSERT INTO correction_groups (theme, status, count, correction_dates, source, created_at, updated_at) "
        "VALUES (?, 'accumulating', 1, ?, 'manual', ?, ?)",
        (theme, json.dumps([date]), now, now)
    )
    group_id = cursor.lastrowid
    conn.commit()
    conn.close()
    print(json.dumps({"status": "ok", "group_id": group_id, "count": 1, "new": True}))
PYEOF
