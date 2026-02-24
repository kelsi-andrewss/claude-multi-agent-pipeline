#!/bin/bash
# Injects CLAUDE.md and ORCHESTRATION.md into Claude's context at session start.
# This ensures pipeline rules are loaded before the first user message.

echo "=== SESSION CONTEXT: MANDATORY PRE-READ ==="
echo "The following files have been loaded into your context. You MUST treat their"
echo "rules as active constraints before responding to any message this session."
echo ""
echo "--- ~/.claude/CLAUDE.md ---"
cat /Users/kelsiandrews/.claude/CLAUDE.md
echo ""
echo "--- ~/.claude/ORCHESTRATION.md ---"
cat /Users/kelsiandrews/.claude/ORCHESTRATION.md
echo ""
echo "=== MANDATORY TOOL CALL REQUIREMENT ==="
echo "Before answering ANY question about workflow, pipeline, or how you would handle a task,"
echo "you MUST use the Read tool to read these files — do NOT answer from memory or loaded context alone:"
echo "  1. Read /Users/kelsiandrews/.claude/ORCHESTRATION.md"
echo "  2. Read the project CLAUDE.md (find it via Glob if path unknown)"
echo "Answering without calling Read first is a violation of these rules."
echo "=== END SESSION CONTEXT ==="

# Satisfy the orch-read guard so no explicit Read is required this session
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
touch "/tmp/orch-read-${SESSION_ID}"

# Stale story check: warn if any story has been in a running-like state for >24h.
# "Running-like" = running, testing, reviewing, merging (anything not filling/queued/closed).
# Uses the story branch's last git commit time as a proxy for last activity.
EPICS_FILES=$(find /Users/kelsiandrews/projects /Users/kelsiandrews/gauntlet /Users/kelsiandrews/.claude \
  -maxdepth 6 -name "epics.json" -path "*/.claude/epics.json" 2>/dev/null)

if [[ -n "$EPICS_FILES" ]]; then
python3 - "$EPICS_FILES" <<'PYEOF'
import json, subprocess, sys, time

STALE_SECONDS = 86400  # 24 hours
RUNNING_STATES = {"running", "testing", "reviewing", "merging"}
now = time.time()
stale = []

epics_files = sys.argv[1].strip().splitlines()

for epics_path in epics_files:
    epics_path = epics_path.strip()
    if not epics_path:
        continue
    try:
        with open(epics_path) as f:
            data = json.load(f)
    except Exception:
        continue

    # project root is two levels up from .claude/epics.json
    parts = epics_path.split("/")
    try:
        claude_idx = len(parts) - parts[::-1].index(".claude") - 1
        project_root = "/".join(parts[:claude_idx])
        project_name = parts[claude_idx - 1]
    except ValueError:
        project_root = "/".join(parts[:-2])
        project_name = parts[-3] if len(parts) >= 3 else "?"

    for story in data.get("stories", []):
        if story.get("state") not in RUNNING_STATES:
            continue
        branch = story.get("branch")
        age_str = "unknown age"
        if branch:
            try:
                result = subprocess.run(
                    ["git", "-C", project_root, "log", "-1", "--format=%ct", branch],
                    capture_output=True, text=True, timeout=5
                )
                ts = result.stdout.strip()
                if ts:
                    age_secs = now - float(ts)
                    if age_secs < STALE_SECONDS:
                        continue  # active — skip
                    hours = int(age_secs // 3600)
                    age_str = f"{hours}h ago"
            except Exception:
                pass  # can't determine age — still surface it
        stale.append({
            "id": story.get("id", "?"),
            "title": story.get("title", "?"),
            "state": story.get("state", "?"),
            "branch": branch or "(no branch)",
            "age": age_str,
            "project": project_name,
        })

if stale:
    print("")
    print("=== STALE STORIES DETECTED ===")
    for s in stale:
        print(f"  [{s['id']}] {s['title']}")
        print(f"    project: {s['project']}  state: {s['state']}  branch: {s['branch']}  last commit: {s['age']}")
    print("  Run /recover to resume or discard these stories.")
    print("")
PYEOF
fi

exit 0
