#!/bin/bash
# Injects CLAUDE.md into Claude's context at session start.
# Orchestration-specific context (ORCHESTRATION.md, behavioral-prefs, agenda)
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
  if [[ -f "$HOME/.claude/behavioral-prefs.md" ]]; then
    echo "--- ~/.claude/behavioral-prefs.md ---"
    cat "$HOME/.claude/behavioral-prefs.md"
    echo ""
  fi
  if [[ -f "$HOME/.claude/session-handoff.md" ]]; then
    echo "=== SESSION HANDOFF (from previous session) ==="
    cat "$HOME/.claude/session-handoff.md"
    echo ""
  fi
  echo "=== MANDATORY TOOL CALL REQUIREMENT ==="
  echo "Before answering ANY question about workflow, pipeline, or how you would handle a task,"
  echo "you MUST use the Read tool to read these files — do NOT answer from memory or loaded context alone:"
  echo "  1. Read ~/.claude/ORCHESTRATION.md"
  echo "  2. Read the project CLAUDE.md (find it via Glob if path unknown)"
  echo "Answering without calling Read first is a violation of these rules."

  # Satisfy the orch-read guard so no explicit Read is required this session
  SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
  touch "/tmp/orch-read-${SESSION_ID}"

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

  # OpenMemory DB path (used by compact OM query below)
  OM_DB="$HOME/.claude/.claude/openmemory.sqlite"

  # Snapshot behavioral file mtimes for session-learning-check Stop hook
  if stat -f %m / >/dev/null 2>&1; then
    _mtime() { stat -f %m "$1" 2>/dev/null || echo "0"; }
  elif stat -c %Y / >/dev/null 2>&1; then
    _mtime() { stat -c %Y "$1" 2>/dev/null || echo "0"; }
  else
    _mtime() { python3 -c "import os; print(int(os.path.getmtime('$1')))" 2>/dev/null || echo "0"; }
  fi
  SNAPSHOT="/tmp/session-mtimes-${SESSION_ID}"
  OUTCOMES_MTIME=$(_mtime "$HOME/.claude/outcomes.md")
  CORRECTIONS_MTIME=$(_mtime "$HOME/.claude/corrections.md")
  cat > "$SNAPSHOT" <<SNAP
OUTCOMES_MTIME=$OUTCOMES_MTIME
CORRECTIONS_MTIME=$CORRECTIONS_MTIME
SNAP

  # Session agenda + stale detection + distillation trigger (single Python block)
  DB_FILE="$HOME/.claude/.claude/epics.db"

  if [[ -f "$DB_FILE" ]]; then
  python3 - "$DB_FILE" "$HOME/.claude" <<'PYEOF'
import os, subprocess, sys, time, re
from datetime import datetime, timezone

STALE_SECONDS = 86400  # 24 hours
RECENTLY_COMPLETED_HOURS = 48
RUNNING_STATES = "('in-progress','in-review','approved','running','testing','reviewing','merging')"
now = time.time()

db_path = sys.argv[1]
project_root = sys.argv[2]

def query_db(sql):
    try:
        result = subprocess.run(
            ["sqlite3", "-separator", "\t", db_path, sql],
            capture_output=True, text=True, timeout=5
        )
        return [line.split("\t") for line in result.stdout.strip().splitlines() if line.strip()]
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

def get_dependency_status(story_id):
    """Return dependency info for a story: list of (dep_id, dep_state) tuples."""
    rows = query_db(
        f"SELECT depends_on FROM stories WHERE id='{story_id}' AND archived=0;"
    )
    if not rows or not rows[0][0]:
        return []
    dep_ids = [d.strip() for d in rows[0][0].split(",") if d.strip()]
    deps = []
    for dep_id in dep_ids:
        dep_rows = query_db(
            f"SELECT state FROM stories WHERE id='{dep_id}';"
        )
        dep_state = dep_rows[0][0] if dep_rows else "unknown"
        deps.append((dep_id, dep_state))
    return deps

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

# --- Ready stories (with dependency status) ---
ready_rows = query_db(
    "SELECT id, title FROM stories WHERE state='ready' AND archived=0 ORDER BY id;"
)
ready_stories = []
for row in ready_rows:
    if len(row) < 2:
        continue
    sid, title = row[0], row[1]
    deps = get_dependency_status(sid)
    non_terminal = [(d, s) for d, s in deps if s not in ("done", "shipped")]
    if non_terminal:
        dep_str = ", ".join(f"{d} ({s})" for d, s in non_terminal)
        status = f"(blocked by: {dep_str})"
    else:
        status = "(no blockers)"
    ready_stories.append({"id": sid, "title": title, "dep_status": status})

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
        print(f"  [{s['id']}] {s['title']}")
        print(f"    state: {s['state']}  branch: {s['branch']}  last commit: {s['age']}")
    print("  Run /recover to resume or discard these stories.")

if has_content:
    print("")
    print("=== SESSION AGENDA ===")

    if active_in_progress:
        print("  In progress:")
        for s in active_in_progress:
            print(f"    [{s['id']}] {s['title']}  (last commit: {s['age']})")

    if ready_stories:
        print("  Ready to run:")
        for s in ready_stories:
            print(f"    [{s['id']}] {s['title']}  {s['dep_status']}")

    if completed_rows:
        print("  Recently completed:")
        for row in completed_rows:
            if len(row) >= 2:
                print(f"    [{row[0]}] {row[1]}")
    print("")

# --- Distillation trigger ---
behavioral_prefs = os.path.join(project_root, "behavioral-prefs.md")
outcomes = os.path.join(project_root, "outcomes.md")
corrections = os.path.join(project_root, "corrections.md")

last_distilled = None
if os.path.isfile(behavioral_prefs):
    try:
        with open(behavioral_prefs) as f:
            content = f.read()
        match = re.search(r'<!-- last-distilled: (\d{4}-\d{2}-\d{2}) -->', content)
        if match:
            last_distilled = match.group(1)
    except Exception:
        pass

def count_entries_since(filepath, since_date):
    """Count ## entries newer than since_date (by scanning ## [date] headers)."""
    if not os.path.isfile(filepath):
        return 0
    try:
        with open(filepath) as f:
            lines = f.readlines()
    except Exception:
        return 0
    count = 0
    for line in lines:
        if line.startswith("## "):
            if since_date is None:
                count += 1  # no prior distillation — count all
            else:
                # Try to extract date from header (## YYYY-MM-DD or ## [YYYY-MM-DD])
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if date_match and date_match.group(1) > since_date:
                    count += 1
                elif not date_match:
                    count += 1  # undated entry — assume new
    return count

unprocessed = count_entries_since(outcomes, last_distilled) + count_entries_since(corrections, last_distilled)

triggered = unprocessed >= 5
if last_distilled and not triggered:
    from datetime import timedelta
    try:
        ld_date = datetime.strptime(last_distilled, "%Y-%m-%d")
        if (datetime.now() - ld_date).days >= 7:
            triggered = True
    except ValueError:
        pass

if triggered:
    print("")
    print("=== BEHAVIORAL DISTILLATION DUE ===")
    if unprocessed >= 5:
        print(f"  {unprocessed} unprocessed entries in outcomes.md + corrections.md")
    else:
        print(f"  Last distillation was {last_distilled} (>7 days ago)")
    print("  Review and distill before starting work.")
    print("")
PYEOF

  # Compact OpenMemory query — top 5 behavioral prefs + top 5 tool learnings
  if [[ -f "$OM_DB" ]]; then
  python3 - "$OM_DB" <<'OMCOMPACTEOF'
import os, subprocess, sys, time

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

def om_query(sql):
    try:
        r = subprocess.run(
            ["sqlite3", "-separator", "\t", om_db, sql],
            capture_output=True, text=True, timeout=5
        )
        return [line.split("\t") for line in r.stdout.strip().splitlines() if line.strip()]
    except Exception:
        return []

def trunc(s, n=150):
    return s[:n] + "..." if len(s) > n else s

prefs = om_query(
    f"SELECT content FROM memories "
    f"WHERE tags LIKE '%behavioral-pref%' AND tags NOT LIKE '%bootstrap%' "
    f"ORDER BY {DECAY_SCORE} DESC LIMIT 5;"
)
learnings = om_query(
    f"SELECT content FROM memories "
    f"WHERE tags LIKE '%tool-learning%' AND tags NOT LIKE '%bootstrap%' "
    f"ORDER BY {DECAY_SCORE} DESC LIMIT 5;"
)

if prefs or learnings:
    print("")
    print("=== MEMORY SNAPSHOT ===")
    if prefs:
        print("  Behavioral prefs:")
        for row in prefs:
            print(f"    - {trunc(row[0])}")
    if learnings:
        print("  Tool learnings:")
        for row in learnings:
            print(f"    - {trunc(row[0])}")
    print("=== END MEMORY SNAPSHOT ===")
OMCOMPACTEOF
  fi

  # Auto-distillation check — flag recently auto-distilled entries for review
  if [[ -f "$HOME/.claude/behavioral-prefs.md" ]] && grep -q "(auto-distilled)" "$HOME/.claude/behavioral-prefs.md" 2>/dev/null; then
    echo ""
    echo "=== AUTO-DISTILLED ENTRIES PENDING REVIEW ==="
    grep "(auto-distilled)" "$HOME/.claude/behavioral-prefs.md"
    echo "  Review and remove the (auto-distilled) marker once confirmed."
  fi

  # Correction patterns — from correction_groups DB table
  if [[ -f "$DB_FILE" ]]; then
  python3 - "$DB_FILE" <<'CORRPATTERNSEOF'
import subprocess, sys

db_path = sys.argv[1]

def query_db(sql):
    try:
        result = subprocess.run(
            ["sqlite3", "-separator", "\t", db_path, sql],
            capture_output=True, text=True, timeout=5
        )
        return [line.split("\t") for line in result.stdout.strip().splitlines() if line.strip()]
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
    print("  Process pending promotions: write preference text to behavioral-prefs.md")
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
