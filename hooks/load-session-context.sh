#!/bin/bash
# Injects CLAUDE.md into Claude's context at session start.
# Orchestration-specific context (ORCHESTRATION.md, behavioral-prefs, agenda)
# is only loaded when working inside the ~/.claude/ project.

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

  # Snapshot behavioral file mtimes for session-learning-check Stop hook
  if stat -f %m / >/dev/null 2>&1; then
    _mtime() { stat -f %m "$1" 2>/dev/null || echo "0"; }
  elif stat -c %Y / >/dev/null 2>&1; then
    _mtime() { stat -c %Y "$1" 2>/dev/null || echo "0"; }
  else
    _mtime() { python3 -c "import os; print(int(os.path.getmtime('$1')))" 2>/dev/null || echo "0"; }
  fi
  SNAPSHOT="/tmp/session-mtimes-${SESSION_ID}"
  DISAGREE_MTIME=$(_mtime "$HOME/.claude/disagreements.md")
  OUTCOMES_MTIME=$(_mtime "$HOME/.claude/outcomes.md")
  cat > "$SNAPSHOT" <<SNAP
DISAGREE_MTIME=$DISAGREE_MTIME
OUTCOMES_MTIME=$OUTCOMES_MTIME
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
disagreements = os.path.join(project_root, "disagreements.md")
outcomes = os.path.join(project_root, "outcomes.md")

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

unprocessed = count_entries_since(disagreements, last_distilled) + count_entries_since(outcomes, last_distilled)

if unprocessed >= 5:
    print("")
    print("=== BEHAVIORAL DISTILLATION DUE ===")
    print(f"  {unprocessed} unprocessed entries in disagreements.md + outcomes.md")
    print("  Review and distill before starting work.")
    print("")
PYEOF
  fi
fi

echo "=== END SESSION CONTEXT ==="

exit 0
