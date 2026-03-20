#!/bin/bash
# Injects CLAUDE.md into Claude's context at session start.
# Orchestration-specific context (ORCHESTRATION.md, rendered-prefs sidecar, agenda)
# is only loaded when working inside the ~/.claude/ project.

source "$(dirname "$0")/lib/profile.sh"
require_profile 1

# Display active hook profile
ACTIVE_PROFILE="standard"
if [[ -f /tmp/claude-hook-profile ]]; then
  ACTIVE_PROFILE=$(cat /tmp/claude-hook-profile 2>/dev/null)
fi
if [[ -n "$CLAUDE_HOOK_PROFILE" && "$ACTIVE_PROFILE" == "standard" ]]; then
  ACTIVE_PROFILE="$CLAUDE_HOOK_PROFILE"
fi
echo "Hook profile: $ACTIVE_PROFILE"
echo ""

# Reconciliation: warn about dead hook references in settings.json
(
  python3 - "$HOME/.claude/settings.json" <<'RECONCILEEOF'
import json, os, sys
try:
    with open(sys.argv[1]) as f:
        cfg = json.load(f)
    hooks = cfg.get("hooks", {})
    home = os.path.expanduser("~")
    dead = []
    for event, entries in hooks.items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                resolved = cmd.replace("~", home, 1) if cmd.startswith("~") else cmd
                if resolved and not os.path.isfile(resolved):
                    dead.append(cmd)
    if dead:
        print("=== DEAD HOOK REFERENCES IN settings.json ===")
        for d in dead:
            print(f"  WARN: {d} does not exist on disk")
        print("  Run story cleanup to remove these entries.")
        print("")
except Exception:
    pass  # Never block session start
RECONCILEEOF
) 2>/dev/null || true

echo "=== SESSION CONTEXT: MANDATORY PRE-READ ==="
echo "The following files have been loaded into your context. You MUST treat their"
echo "rules as active constraints before responding to any message this session."
echo ""
echo "--- ~/.claude/CLAUDE.md ---"
cat "$HOME/.claude/CLAUDE.md"
echo ""

# Orchestration context — only when working in the ~/.claude/ project
if [[ "$PWD" == "$HOME/.claude" || "$PWD" == "$HOME/.claude/"* ]]; then
  echo "--- ~/.claude/ORCHESTRATION.md ---"
  cat "$HOME/.claude/ORCHESTRATION.md"
  echo ""
  # Migrate correction_groups schema: add text/source columns if missing
  DB_FILE_PREFS="$HOME/.claude/.claude/epics.db"
  if [[ -f "$DB_FILE_PREFS" ]]; then
  python3 - "$DB_FILE_PREFS" <<'MIGRATEEOF'
import sqlite3, sys
db_path = sys.argv[1]
conn = sqlite3.connect(db_path, timeout=5)
for col, default in [("text", "''"), ("source", "'auto'")]:
    try:
        conn.execute(f"ALTER TABLE correction_groups ADD COLUMN {col} TEXT DEFAULT {default}")
    except sqlite3.OperationalError:
        pass
conn.execute("CREATE INDEX IF NOT EXISTS idx_correction_groups_status ON correction_groups(status)")
conn.execute(
    "UPDATE correction_groups "
    "SET text = 'User corrected ' || count || 'x on: ' || substr(theme, 1, 200) "
    "WHERE status = 'promoted' AND (text IS NULL OR text = '')"
)
conn.execute("""
    CREATE TABLE IF NOT EXISTS decision_preferences (
        id TEXT PRIMARY KEY,
        decision_type TEXT NOT NULL,
        context TEXT NOT NULL,
        chosen_path TEXT NOT NULL,
        alternatives TEXT,
        session_id TEXT,
        confidence REAL DEFAULT 0.5,
        signal_score REAL DEFAULT 0,
        signal_count INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_dp_type ON decision_preferences(decision_type)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_dp_created ON decision_preferences(created_at)")
conn.commit()
conn.close()
MIGRATEEOF

  # One-time: fix correction_groups count mismatches (count should equal unique dates)
  python3 - "$DB_FILE_PREFS" <<'COUNTFIXEOF'
import json, sqlite3, sys
try:
    conn = sqlite3.connect(sys.argv[1], timeout=5)
    rows = conn.execute(
        "SELECT rowid, correction_dates, count FROM correction_groups"
    ).fetchall()
    fixes = []
    for rowid, dates_json, stored_count in rows:
        try:
            dates = json.loads(dates_json) if dates_json else []
        except (json.JSONDecodeError, TypeError):
            continue
        actual = len(set(dates))
        if actual != stored_count:
            fixes.append((actual, rowid))
    if fixes:
        conn.executemany("UPDATE correction_groups SET count=? WHERE rowid=?", fixes)
        conn.commit()
    conn.close()
except Exception:
    pass
COUNTFIXEOF
  fi

  # Render behavioral preferences from DB to sidecar file
  RENDERED_PREFS="$HOME/.claude/.claude/rendered-prefs.md"
  if [[ -f "$DB_FILE_PREFS" ]]; then
  python3 - "$DB_FILE_PREFS" "$RENDERED_PREFS" <<'RENDERPREFSEOF'
import sqlite3, sys

db_path = sys.argv[1]
out_path = sys.argv[2]

def query_db(sql, params=()):
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []

# Check if text column exists (requires story-711 schema migration)
cols = query_db("PRAGMA table_info(correction_groups);")
col_names = [c[1] for c in cols if len(c) > 1]
if "text" not in col_names:
    # Schema not migrated yet — write empty file and exit
    with open(out_path, "w") as f:
        f.write("# Behavioral Preferences\n\n_Schema migration pending._\n")
    sys.exit(0)

rows = query_db(
    "SELECT text FROM correction_groups "
    "WHERE (status IN ('promoted','pending_promotion') OR source='manual') "
    "AND status != 'dismissed' "
    "ORDER BY updated_at DESC;"
)

with open(out_path, "w") as f:
    f.write("# Behavioral Preferences\n\n")
    if rows:
        for row in rows:
            text = row[0].strip()
            if text:
                f.write(f"- {text}\n")
    else:
        f.write("_No preferences recorded yet._\n")
RENDERPREFSEOF
  else
    # No DB — write empty sidecar
    echo "# Behavioral Preferences" > "$RENDERED_PREFS"
    echo "" >> "$RENDERED_PREFS"
    echo "_No database available._" >> "$RENDERED_PREFS"
  fi

  # Render decision health scores (negative signals) to sidecar
  if [[ -f "$DB_FILE_PREFS" ]]; then
  python3 - "$DB_FILE_PREFS" "$RENDERED_PREFS" <<'DECISIONHEALTHEOF'
import sqlite3, sys
try:
    db_path = sys.argv[1]
    out_path = sys.argv[2]
    conn = sqlite3.connect(db_path, timeout=5)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decision_preferences'")
    if not cur.fetchone():
        conn.close()
        sys.exit(0)
    cur.execute(
        "SELECT decision_type, context, signal_score FROM decision_preferences "
        "WHERE signal_score < 0 ORDER BY signal_score ASC LIMIT 10"
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        sys.exit(0)
    with open(out_path, "a") as f:
        f.write("\n\n# Decision Health\n\n")
        for decision_type, context, signal_score in rows:
            ctx = context[:80] + "..." if len(context) > 80 else context
            f.write(f"- {decision_type}: {ctx} (signal: {signal_score})\n")
except Exception:
    pass
DECISIONHEALTHEOF
  fi

  # Stale decisions sidecar (generated by stop_processor.py Stage 6)
  STALE_DECISIONS="$HOME/.claude/.claude/stale-decisions.md"
  if [[ -s "$STALE_DECISIONS" ]]; then
    echo ""
    echo "--- Stale Decisions ---"
    cat "$STALE_DECISIONS"
    echo ""
  fi

  if [[ -f "$HOME/.claude/session-handoff.md" ]]; then
    echo "=== SESSION HANDOFF (from previous session) ==="
    cat "$HOME/.claude/session-handoff.md"
    echo ""
  fi

  # Compact OpenMemory query — top 5 tool learnings
  OM_DB="$HOME/.claude/.claude/openmemory.sqlite"
  if [[ -f "$OM_DB" ]]; then
  python3 - "$OM_DB" <<'OMCOMPACTEOF'
import os, sys, time

om_db = sys.argv[1]
now = time.time()
DEFAULT_DECAY = 0.05

# Prune expired entries
try:
    project_root = os.path.expanduser("~/.claude")
    sys.path.insert(0, project_root)
    from hooks.lib.om_write import prune_expired
    pruned = prune_expired()
    if pruned > 0:
        print(f"  (pruned {pruned} expired OpenMemory entries)")
except Exception:
    pass

DECAY_SCORE = (
    f"feedback_score * EXP(-COALESCE(decay_lambda, {DEFAULT_DECAY}) "
    f"* (({int(now)} - COALESCE(last_seen_at, created_at)) / 86400.0))"
)

def om_query(sql, params=()):
    try:
        import sqlite3
        conn = sqlite3.connect(om_db, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []

def trunc(s, n=150):
    return s[:n] + "..." if len(s) > n else s

learnings = om_query(
    f"SELECT content FROM memories "
    f"WHERE tags LIKE '%tool-learning%' AND tags NOT LIKE '%bootstrap%' "
    f"ORDER BY {DECAY_SCORE} DESC LIMIT 5;"
)

if learnings:
    print("")
    print("=== MEMORY SNAPSHOT (mandatory context) ===")
    print("  Tool learnings:")
    for row in learnings:
        print(f"    - {trunc(row[0])}")
    print("=== END MEMORY SNAPSHOT ===")
OMCOMPACTEOF
  fi

  # Trust calibration summary
  RUN_STATE_DB="$HOME/.claude/.claude/run-state.db"
  if [[ -f "$RUN_STATE_DB" ]]; then
  python3 - "$RUN_STATE_DB" <<'TRUSTEOF'
import json, os, sys
db_path = sys.argv[1]
try:
    sys.path.insert(0, os.path.expanduser("~/.claude"))
    from hooks.lib.signal_processor import compute_trust_scores, get_trust_level
    report = compute_trust_scores(db_path)
    level = get_trust_level(report)
    overrides = {k: v for k, v in report["domains"].items() if v.get("override")}
    print(f"  Trust: {level} (global: {report['global']:.2f}, {len(report['domains'])} domains, {len(overrides)} overrides)")
    if overrides:
        for domain, info in overrides.items():
            print(f"    Override: {domain}: {info['score']:.2f} ({info['count']} samples)")
except Exception as e:
    print(f"  Trust: medium (default — {e})")
    level = "medium"
# Export for session use
print(f"CLAUDE_TRUST_LEVEL={level}")
TRUSTEOF
  fi

  # Background: compute decision freshness scores (no session output)
  if [[ -f "$HOME/.claude/.claude/decisions.sql" || -f "$HOME/.claude/.claude/decisions.db" ]]; then
    nohup python3 "$HOME/.claude/scripts/decision-freshness.py" --project-root "$HOME/.claude" > "/tmp/decision-freshness-${CLAUDE_SESSION_ID:-$$}.log" 2>&1 &
  fi

  SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')

  # OpenMemory health check — warn if Ollama is unreachable
  if ! curl -s --connect-timeout 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo ""
    echo "=== OPENMEMORY WARNING ==="
    echo "  Ollama not reachable at localhost:11434."
    echo "  Memory queries disabled this session. Run: ollama serve"
    echo ""
  fi

  # Session-start timestamp for debrief freshness check
  echo "$(date +%s)" > "/tmp/session-start-${SESSION_ID}"

  # Background: decision freshness scoring (no session output)
  if [[ -f "$HOME/.claude/.claude/decisions.sql" || -f "$HOME/.claude/.claude/decisions.db" ]]; then
    nohup python3 "$HOME/.claude/scripts/decision-freshness.py" --project-root "$HOME/.claude" > "/tmp/decision-freshness-${SESSION_ID}.log" 2>&1 &
  fi

  # Session agenda + stale detection (single Python block)
  DB_FILE="$HOME/.claude/.claude/epics.db"

  if [[ -f "$DB_FILE" ]]; then
  python3 - "$DB_FILE" "$HOME/.claude" <<'PYEOF'
import sqlite3, subprocess, sys, time
from datetime import datetime, timezone

STALE_SECONDS = 86400  # 24 hours
RECENTLY_COMPLETED_HOURS = 48
RUNNING_STATES = "('in-progress','in-review','approved','running','testing','reviewing','merging')"
now = time.time()

db_path = sys.argv[1]
project_root = sys.argv[2]

def query_db(sql, params=()):
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []

def branch_age_hours(branch):
    """Return hours since last commit on branch, or None if unknown."""
    try:
        r = subprocess.run(
            ["git", "-C", project_root, "log", "-1", "--format=%ct", branch],
            capture_output=True, text=True, timeout=5
        )
        ts = r.stdout.strip()
        if ts:
            return (now - float(ts)) / 3600
    except Exception:
        pass
    return None

# --- In-progress stories (with stale detection) ---
in_progress_rows = query_db(
    f"SELECT id, title, state, branch FROM stories WHERE state IN {RUNNING_STATES} AND archived=0 ORDER BY id;"
)
stale = []
active_in_progress = []
for row in in_progress_rows:
    if len(row) < 4:
        continue
    sid, title, state, branch = row[0], row[1], row[2], row[3]
    hours = branch_age_hours(branch) if branch else None
    age_str = f"{int(hours)}h ago" if hours is not None else "unknown age"
    entry = {"id": sid, "title": title, "state": state, "branch": branch or "(no branch)", "age": age_str, "hours": hours}
    if hours is not None and hours >= (STALE_SECONDS / 3600):
        stale.append(entry)
    else:
        active_in_progress.append(entry)

# --- Ready stories ---
ready_rows = query_db(
    "SELECT id, title FROM stories WHERE state='ready' AND archived=0 ORDER BY id;"
)
ready_stories = []
for row in ready_rows:
    if len(row) < 2:
        continue
    sid, title = row[0], row[1]
    ready_stories.append({"id": sid, "title": title})

# --- Recently completed (last 48h, limit 5) ---
cutoff_iso = datetime.fromtimestamp(now - RECENTLY_COMPLETED_HOURS * 3600, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
completed_rows = query_db(
    f"SELECT id, title FROM stories WHERE state IN ('done','shipped') AND archived=0 AND completed_at >= '{cutoff_iso}' ORDER BY completed_at DESC LIMIT 5;"
)

# --- Print agenda ---
has_content = stale or active_in_progress or ready_stories or completed_rows

if stale:
    print("")
    print("=== STALE STORIES DETECTED ===")
    for s in stale:
        print(f"  [{s['id']}] {s['title']} (stale: {s['age']})")
    print("  Run /recover to resume or discard these stories.")

if has_content:
    print("")
    print("=== SESSION AGENDA ===")

    if active_in_progress:
        print("  In progress:")
        for s in active_in_progress:
            print(f"    [{s['id']}] {s['title']}")

    if ready_stories:
        print("  Ready to run:")
        for s in ready_stories:
            print(f"    [{s['id']}] {s['title']}")

    if completed_rows:
        print("  Recently completed:")
        for row in completed_rows:
            if len(row) >= 2:
                print(f"    [{row[0]}] {row[1]}")
    print("")

PYEOF

  # Correction patterns — from correction_groups DB table
  if [[ -f "$DB_FILE" ]]; then
  python3 - "$DB_FILE" <<'CORRPATTERNSEOF'
import sqlite3, sys

db_path = sys.argv[1]

def query_db(sql, params=()):
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []

# Check if correction_groups table exists
tables = query_db(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='correction_groups';"
)
if not tables:
    sys.exit(0)

rows = query_db(
    "SELECT theme, status, count, correction_dates, promoted_at "
    "FROM correction_groups "
    "WHERE status != 'dismissed' "
    "ORDER BY CASE status WHEN 'pending_promotion' THEN 0 WHEN 'accumulating' THEN 1 WHEN 'promoted' THEN 2 END, count DESC;"
)
if not rows:
    sys.exit(0)

pending = [r for r in rows if r[1] == "pending_promotion"]
accumulating = [r for r in rows if r[1] == "accumulating"]
promoted = [r for r in rows if r[1] == "promoted"]

if not pending and not accumulating:
    sys.exit(0)

print("")
print("=== CORRECTION PATTERNS (triaged) ===")
if pending:
    print("  Pending promotion:")
    for r in pending:
        theme, status, count, dates = r[0], r[1], r[2], r[3]
        promoted_at = r[4] if len(r) > 4 else ""
        print(f'    [{count}x] "{theme}" (evidence: {dates})')
    print("  Process pending promotions: use /prefs to review and promote")
if accumulating:
    print("  Accumulating:")
    for r in accumulating:
        theme, status, count, dates = r[0], r[1], r[2], r[3]
        needed = 3 - int(count)
        if needed < 1:
            needed = 1
        print(f'    [{count}x] "{theme}" (need {needed} more)')
if promoted and (pending or accumulating):
    print("  Already promoted:")
    for r in promoted:
        theme, status, count, dates = r[0], r[1], r[2], r[3]
        promoted_at = r[4] if len(r) > 4 else ""
        print(f'    [{count}x] "{theme}" (promoted {promoted_at})')
print("=== END CORRECTION PATTERNS ===")
CORRPATTERNSEOF
  fi

  fi
fi

echo "=== END SESSION CONTEXT ==="

exit 0
