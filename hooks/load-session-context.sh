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

  # Session-start timestamp for debrief freshness check
  echo "$(date +%s)" > "/tmp/session-start-${SESSION_ID}"

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
  CORRECTIONS_MTIME=$(_mtime "$HOME/.claude/corrections.md")
  FRICTION_MTIME=$(_mtime "$HOME/.claude/friction-log.md")
  HANDOFF_MTIME=$(_mtime "$HOME/.claude/session-handoff.md")
  cat > "$SNAPSHOT" <<SNAP
DISAGREE_MTIME=$DISAGREE_MTIME
OUTCOMES_MTIME=$OUTCOMES_MTIME
CORRECTIONS_MTIME=$CORRECTIONS_MTIME
FRICTION_MTIME=$FRICTION_MTIME
HANDOFF_MTIME=$HANDOFF_MTIME
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

  # Memory Briefing — query openmemory.sqlite directly for session-start context
  OM_DB="$HOME/.claude/.claude/openmemory.sqlite"
  if [[ -f "$OM_DB" ]]; then
  # Gather signal context for memory queries
  SIGNAL_BRANCH=$(git -C "$HOME/.claude" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  SIGNAL_DIR=$(basename "$PWD")
  SIGNAL_RECENT_FILES=$(git -C "$HOME/.claude" diff --name-only HEAD~1 2>/dev/null | head -20 || echo "")

  python3 - "$OM_DB" "$DB_FILE" "$SIGNAL_BRANCH" "$SIGNAL_DIR" "$SIGNAL_RECENT_FILES" <<'MEMBRIEFEOF'
import math, os, subprocess, sys, time

om_db = sys.argv[1]
epics_db = sys.argv[2] if len(sys.argv) > 2 else None
signal_branch = sys.argv[3] if len(sys.argv) > 3 else ""
signal_dir = sys.argv[4] if len(sys.argv) > 4 else ""
signal_files = sys.argv[5] if len(sys.argv) > 5 else ""

now = time.time()
DEFAULT_DECAY = 0.05  # ~14-day half-life

def om_query(sql):
    try:
        r = subprocess.run(
            ["sqlite3", "-separator", "\t", om_db, sql],
            capture_output=True, text=True, timeout=5
        )
        return [line.split("\t") for line in r.stdout.strip().splitlines() if line.strip()]
    except Exception:
        return []

def trunc(s, n=200):
    return s[:n] + "..." if len(s) > n else s

# Decay-weighted scoring SQL fragment
DECAY_SCORE = (
    f"feedback_score * EXP(-COALESCE(decay_lambda, {DEFAULT_DECAY}) "
    f"* (({int(now)} - COALESCE(last_seen_at, created_at)) / 86400.0))"
)

# 1. Last 3 session summaries (recency-ordered, no decay — these are logs)
sessions = om_query(
    "SELECT content FROM memories "
    "WHERE tags LIKE '%session-summary%' AND tags NOT LIKE '%bootstrap%' "
    "ORDER BY created_at DESC LIMIT 3;"
)

# 2. Top 5 tool learnings by decay-weighted score
learnings = om_query(
    f"SELECT content FROM memories "
    f"WHERE tags LIKE '%tool-learning%' AND tags NOT LIKE '%bootstrap%' "
    f"ORDER BY {DECAY_SCORE} DESC LIMIT 5;"
)

# 3. Top 5 conventions by decay-weighted score
conventions = om_query(
    f"SELECT content FROM memories "
    f"WHERE tags LIKE '%convention%' AND tags NOT LIKE '%bootstrap%' "
    f"ORDER BY {DECAY_SCORE} DESC LIMIT 5;"
)

# 4. Signal-aware tech-relevant memories
# Gather signals from: git branch, recent files, epics.db write_files
EXT_MAP = {
    ".jsx": "react", ".tsx": "react", ".js": "javascript", ".ts": "typescript",
    ".css": "css", ".scss": "css", ".dart": "flutter", ".py": "python",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".swift": "swift", ".rb": "ruby", ".vue": "vue", ".svelte": "svelte",
    ".sh": "bash", ".md": "markdown",
}
signal_terms = set()

# From git branch name (e.g., "feature/auth" → "auth")
if signal_branch and signal_branch not in ("main", "master", "HEAD"):
    for part in signal_branch.replace("/", "-").split("-"):
        if len(part) > 2:
            signal_terms.add(part.lower())

# From recently modified files
if signal_files:
    for f in signal_files.strip().splitlines():
        f = f.strip()
        ext = os.path.splitext(f)[1].lower()
        if ext in EXT_MAP:
            signal_terms.add(EXT_MAP[ext])
        # Also extract directory-level signals (e.g., "hooks/foo.sh" → "hooks")
        dirname = os.path.dirname(f)
        if dirname:
            signal_terms.add(dirname.split("/")[0].lower())

# From epics.db in-progress story write_files
if epics_db and os.path.isfile(epics_db):
    try:
        r = subprocess.run(
            ["sqlite3", "-separator", "\t", epics_db,
             "SELECT write_files FROM stories WHERE state IN "
             "('in-progress','ready','in-review','approved') AND archived=0;"],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.strip().splitlines():
            if not line.strip():
                continue
            for f in line.split(","):
                f = f.strip()
                ext = os.path.splitext(f)[1].lower()
                if ext in EXT_MAP:
                    signal_terms.add(EXT_MAP[ext])
    except Exception:
        pass

tech_memories = []
if signal_terms:
    clauses = " OR ".join(f"LOWER(content) LIKE '%{t}%'" for t in signal_terms)
    tech_memories = om_query(
        f"SELECT content FROM memories "
        f"WHERE ({clauses}) AND tags NOT LIKE '%bootstrap%' AND tags NOT LIKE '%session-summary%' "
        f"ORDER BY {DECAY_SCORE} DESC LIMIT 5;"
    )

# Output
print("")
print("=== MEMORY BRIEFING ===")

print("  Recent sessions:")
if sessions:
    for row in sessions:
        print(f"    - {trunc(row[0])}")
else:
    print("    (none yet)")

print("  Tool learnings:")
if learnings:
    for row in learnings:
        print(f"    - {trunc(row[0])}")
else:
    print("    (none yet)")

print("  Conventions:")
if conventions:
    for row in conventions:
        print(f"    - {trunc(row[0])}")
else:
    print("    (none yet)")

tech_label = ", ".join(sorted(signal_terms)[:5]) if signal_terms else "no active stories"
print(f"  Tech-relevant ({tech_label}):")
if tech_memories:
    for row in tech_memories:
        print(f"    - {trunc(row[0])}")
else:
    print("    (none yet)")

print("=== END MEMORY BRIEFING ===")
MEMBRIEFEOF
  fi


  fi

  # Correction patterns — grouped by theme, counts only
  TALLIES_FILE="$HOME/.claude/correction-tallies.jsonl"
  if [[ -f "$TALLIES_FILE" ]] && [[ -s "$TALLIES_FILE" ]]; then
  python3 - "$TALLIES_FILE" <<'CORRPATTERNSEOF'
import json, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

tallies_file = sys.argv[1]
cutoff = datetime.now(timezone.utc) - timedelta(days=14)
cutoff_str = cutoff.strftime("%Y-%m-%d")

entries = []
try:
    with open(tallies_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("promoted", False):
                    continue
                if entry.get("date", "") < cutoff_str:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue
except Exception:
    sys.exit(0)

if not entries:
    sys.exit(0)

# Group by theme: first 40 chars of message (deduplicates near-identical corrections)
themes = defaultdict(list)
for e in entries:
    key = e.get("user_msg", "")[:40].strip().lower()
    themes[key].append(e)

print("")
print(f"=== CORRECTION PATTERNS ({len(entries)} unprocessed) ===")
# Show themes sorted by count (highest first), with representative message
for key in sorted(themes, key=lambda k: -len(themes[k])):
    group = themes[key]
    representative = group[0].get("user_msg", "")[:80]
    source = group[0].get("source", "unknown")
    if len(group) > 1:
        print(f'  [{len(group)}x] "{representative}" ({source})')
    else:
        date = group[0].get("date", "")
        print(f'  [{date}] "{representative}" ({source})')
print("  Process these before starting work.")
print("=== END CORRECTION PATTERNS ===")
CORRPATTERNSEOF
  fi

  # Unprocessed sessions — last 3 only, with summary line for the rest
  RECORDS_FILE="$HOME/.claude/session-records.md"
  if [[ -f "$RECORDS_FILE" ]]; then
  python3 - "$RECORDS_FILE" <<'UNPROCESSEDEOF'
import re, sys
from datetime import datetime, timezone, timedelta

records_file = sys.argv[1]

now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=72)

try:
    with open(records_file) as f:
        content = f.read()
except Exception:
    sys.exit(0)

# Parse session records
entries = []
current = None
for line in content.splitlines():
    header = re.match(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) — (.+)', line)
    if header:
        if current:
            entries.append(current)
        current = {"date": header.group(1), "summary": header.group(2), "lines": [], "artifacts": ""}
    elif current:
        current["lines"].append(line)
        if line.startswith("Artifacts updated:"):
            current["artifacts"] = line.split(":", 1)[1].strip()
if current:
    entries.append(current)

# Filter: last 72h, artifacts = "none"
unprocessed = []
total_friction = 0
for e in entries:
    try:
        dt = datetime.strptime(e["date"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        if dt < cutoff:
            continue
    except ValueError:
        continue
    if e["artifacts"] == "none":
        for line in e["lines"]:
            if line.startswith("Friction clusters:"):
                try:
                    total_friction += int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        unprocessed.append(e)

if not unprocessed:
    sys.exit(0)

print("")
print("=== UNPROCESSED SESSIONS ===")

# Show last 3 in detail
shown = unprocessed[-3:]
rest = unprocessed[:-3] if len(unprocessed) > 3 else []

if rest:
    print(f"  ({len(rest)} older sessions not shown, {total_friction} total friction clusters)")

for e in shown:
    friction_line = ""
    for line in e["lines"]:
        if line.startswith("Friction clusters:"):
            friction_line = line.split(":", 1)[1].strip()
    key_lines = []
    in_keys = False
    for line in e["lines"]:
        if line.startswith("Key exchanges:"):
            in_keys = True
            continue
        if in_keys:
            if line.startswith("  - "):
                key_lines.append(line.strip()[4:].strip('"')[:60])
            else:
                in_keys = False
    print(f"  [{e['date']}] {e['summary']}")
    if friction_line and friction_line != "0":
        print(f"    Friction clusters: {friction_line}")
    if key_lines:
        keys = " / ".join(key_lines[:2])
        print(f"    Key: {keys}")
print("=== END UNPROCESSED SESSIONS ===")
UNPROCESSEDEOF
  fi
fi

echo "=== END SESSION CONTEXT ==="

exit 0
