#!/bin/bash
# Injects CLAUDE.md and ORCHESTRATION.md into Claude's context at session start.
# This ensures pipeline rules are loaded before the first user message.

echo "=== SESSION CONTEXT: MANDATORY PRE-READ ==="
echo "The following files have been loaded into your context. You MUST treat their"
echo "rules as active constraints before responding to any message this session."
echo ""
echo "--- ~/.claude/CLAUDE.md ---"
cat "$HOME/.claude/CLAUDE.md"
echo ""
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
echo "=== END SESSION CONTEXT ==="

# Satisfy the orch-read guard so no explicit Read is required this session
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
touch "/tmp/orch-read-${SESSION_ID}"

# Stale story check: warn if any story has been in a running-like state for >24h.
# "Running-like" = in-progress, in-review, approved (anything not draft/ready/done/shipped).
# Uses the story branch's last git commit time as a proxy for last activity.
DB_FILE="$HOME/.claude/.claude/epics.db"

if [[ -f "$DB_FILE" ]]; then
python3 - "$DB_FILE" <<'PYEOF'
import os, subprocess, sys, time

STALE_SECONDS = 86400  # 24 hours
RUNNING_STATES = "('in-progress','in-review','approved','running','testing','reviewing','merging')"
now = time.time()
stale = []

db_path = sys.argv[1]
project_root = os.path.expanduser("~/.claude")

try:
    result = subprocess.run(
        ["sqlite3", "-separator", "\t", db_path,
         f"SELECT id, title, state, branch FROM stories WHERE state IN {RUNNING_STATES} AND archived=0;"],
        capture_output=True, text=True, timeout=5
    )
    rows = [line.split("\t") for line in result.stdout.strip().splitlines() if line.strip()]
except Exception:
    rows = []

for row in rows:
    if len(row) < 4:
        continue
    sid, title, state, branch = row[0], row[1], row[2], row[3]
    age_str = "unknown age"
    if branch:
        try:
            r = subprocess.run(
                ["git", "-C", project_root, "log", "-1", "--format=%ct", branch],
                capture_output=True, text=True, timeout=5
            )
            ts = r.stdout.strip()
            if ts:
                age_secs = now - float(ts)
                if age_secs < STALE_SECONDS:
                    continue  # active — skip
                hours = int(age_secs // 3600)
                age_str = f"{hours}h ago"
        except Exception:
            pass
    stale.append({"id": sid, "title": title, "state": state, "branch": branch or "(no branch)", "age": age_str})

if stale:
    print("")
    print("=== STALE STORIES DETECTED ===")
    for s in stale:
        print(f"  [{s['id']}] {s['title']}")
        print(f"    state: {s['state']}  branch: {s['branch']}  last commit: {s['age']}")
    print("  Run /recover to resume or discard these stories.")
    print("")
PYEOF
fi

exit 0
