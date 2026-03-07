#!/bin/bash
# Stop hook — session learning extraction.
# Reads transcript JSONL from stdin, detects corrections, syncs learnings.

source "$(dirname "$0")/lib/profile.sh"
require_profile 1

# Read stdin for transcript_path and session metadata
INPUT=$(cat)
TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('transcript_path', ''))" 2>/dev/null)
SESSION_ID_RAW=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('session_id', ''))" 2>/dev/null)
CWD=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('cwd', ''))" 2>/dev/null)

# ── Section 1: Mtime comparison ──────────────────────────────────────────────
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
SNAPSHOT="/tmp/session-mtimes-${SESSION_ID}"
ARTIFACTS_CHANGED=""

if [[ -f "$SNAPSHOT" ]]; then
  source "$SNAPSHOT"

  if stat -f %m / >/dev/null 2>&1; then
    mtime() { stat -f %m "$1" 2>/dev/null || echo "0"; }
  elif stat -c %Y / >/dev/null 2>&1; then
    mtime() { stat -c %Y "$1" 2>/dev/null || echo "0"; }
  else
    mtime() { python3 -c "import os; print(int(os.path.getmtime('$1')))" 2>/dev/null || echo "0"; }
  fi

  CURRENT_CORRECTIONS=$(mtime "$HOME/.claude/corrections.md")
  CURRENT_OUTCOMES=$(mtime "$HOME/.claude/outcomes.md")
  CURRENT_PREFS=$(mtime "$HOME/.claude/behavioral-prefs.md")

  CORRECTIONS_CHANGED=false
  OUTCOMES_CHANGED=false
  [[ "$CURRENT_CORRECTIONS" != "${CORRECTIONS_MTIME:-0}" ]] && CORRECTIONS_CHANGED=true
  [[ "$CURRENT_OUTCOMES" != "${OUTCOMES_MTIME:-0}" ]] && OUTCOMES_CHANGED=true

  [[ "$CORRECTIONS_CHANGED" == true ]] && ARTIFACTS_CHANGED="corrections"
  [[ "$OUTCOMES_CHANGED" == true ]] && ARTIFACTS_CHANGED="${ARTIFACTS_CHANGED:+$ARTIFACTS_CHANGED, }outcomes"
  [[ "$CURRENT_PREFS" != "${PREFS_MTIME:-0}" ]] && ARTIFACTS_CHANGED="${ARTIFACTS_CHANGED:+$ARTIFACTS_CHANGED, }behavioral-prefs"

  if [[ "$CORRECTIONS_CHANGED" == true && "$OUTCOMES_CHANGED" == false ]]; then
    echo "corrections.md modified — outcomes.md unchanged"
    echo "→ Log an outcome for this session's correction(s) next session."
  elif [[ "$CORRECTIONS_CHANGED" == true && "$OUTCOMES_CHANGED" == true ]]; then
    echo "corrections.md + outcomes.md both updated"
    echo "→ Distillation will trigger at threshold."
  elif [[ "$OUTCOMES_CHANGED" == true ]]; then
    echo "outcomes.md updated → distillation will trigger at threshold."
  fi

  rm -f "$SNAPSHOT"
fi

# ── Section 2: Correction detection → correction_groups ──────────────────────
# Writes correction count to a temp file for downstream sections.
CORRECTION_COUNT=0
CORRECTION_COUNT_FILE="/tmp/correction-count-$$"
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
python3 - "$TRANSCRIPT_PATH" "$HOME/.claude" "${SESSION_ID_RAW:-}" "${CORRECTIONS_MTIME:-0}" "$CORRECTION_COUNT_FILE" <<'PYEOF'
import json, os, re, sqlite3, sys
from datetime import datetime, timezone

transcript_path = sys.argv[1]
project_root = sys.argv[2]
session_id = sys.argv[3] if len(sys.argv) > 3 else ""
corrections_mtime_start = sys.argv[4] if len(sys.argv) > 4 else "0"
count_file = sys.argv[5] if len(sys.argv) > 5 else ""

db_path = os.path.expanduser("~/.claude/.claude/epics.db")
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# --- Parse transcript ---
lines = []
try:
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
except Exception:
    print("0"); sys.exit(0)

if not lines:
    print("0"); sys.exit(0)

if len(lines) > 5000:
    lines = lines[-2000:]

# Extract turns with tool_use info
turns = []
for entry in lines:
    role = entry.get("type", "")
    content_text = ""
    has_tool_use = False

    if role == "user":
        msg = entry.get("message", "")
        if isinstance(msg, str):
            content_text = msg
        elif isinstance(msg, dict):
            c = msg.get("content", "")
            if isinstance(c, list):
                content_text = " ".join(
                    p.get("text", "") for p in c
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            elif isinstance(c, str):
                content_text = c
        elif isinstance(msg, list):
            content_text = " ".join(
                p.get("text", "") for p in msg
                if isinstance(p, dict) and p.get("type") == "text"
            )
    elif role == "assistant":
        msg = entry.get("message", {})
        if isinstance(msg, dict):
            c = msg.get("content", [])
            if isinstance(c, list):
                content_text = " ".join(
                    p.get("text", "") for p in c
                    if isinstance(p, dict) and p.get("type") == "text"
                )
                has_tool_use = any(
                    isinstance(p, dict) and p.get("type") == "tool_use"
                    for p in c
                )
            elif isinstance(c, str):
                content_text = c
    else:
        continue

    if content_text:
        turns.append({
            "role": role,
            "content": content_text.strip(),
            "has_tool_use": has_tool_use,
        })

if not turns:
    print("0"); sys.exit(0)

# --- Correction detection patterns ---
IMPERATIVE_STARTS = re.compile(
    r'^(use |stop |don\'t |do not |just |why didn\'t |why don\'t |why aren\'t |'
    r'make |run |try |ship |log |fix |check |read |write |call |add |remove |'
    r'never |always )',
    re.IGNORECASE
)

def is_frustration(msg):
    if msg.rstrip().endswith("!!") or msg.rstrip().endswith("??"):
        return True
    caps_words = [w for w in msg.split() if w.isupper() and len(w) > 1]
    return len(caps_words) >= 2

META_PATTERN = re.compile(
    r"you'?ve been |you'?re not |you keep |you should |you always |you never ",
    re.IGNORECASE
)

SYSTEM_MSG = re.compile(
    r'<(local-command-caveat|task-notification|system-reminder|command-name|command-message)>|'
    r'^Base directory for this skill|'
    r'^Implement the following plan:|'
    r'^<skill-',
    re.IGNORECASE
)

# Detect corrections from transcript
detected = []
prev_assistant_had_tool_use = False
for i, turn in enumerate(turns):
    if turn["role"] == "assistant":
        prev_assistant_had_tool_use = turn["has_tool_use"]
        continue
    if turn["role"] != "user":
        continue

    msg = turn["content"]
    if SYSTEM_MSG.search(msg):
        prev_assistant_had_tool_use = False
        continue

    matched = False
    if len(msg) < 150 and prev_assistant_had_tool_use and IMPERATIVE_STARTS.match(msg):
        matched = True
    if not matched and is_frustration(msg):
        matched = True
    if not matched and META_PATTERN.search(msg):
        matched = True

    if matched:
        detected.append({"msg": msg[:300], "date": today, "source": "structural"})
    prev_assistant_had_tool_use = False

# Manual correction detection from corrections.md
corrections_file = os.path.join(project_root, "corrections.md")
try:
    corrections_mtime_start_val = int(corrections_mtime_start)
except (ValueError, TypeError):
    corrections_mtime_start_val = 0

if os.path.isfile(corrections_file):
    try:
        current_mtime = int(os.path.getmtime(corrections_file))
    except Exception:
        current_mtime = 0

    if current_mtime > corrections_mtime_start_val:
        try:
            with open(corrections_file) as f:
                content = f.read()
            for match in re.finditer(r'^## (\d{4}-\d{2}-\d{2}) — (.+)', content, re.MULTILINE):
                if match.group(1) == today:
                    detected.append({"msg": match.group(2).strip()[:300], "date": today, "source": "manual"})
        except Exception:
            pass

# Write to correction_groups table in epics.db
if detected and os.path.isfile(db_path):
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS correction_groups ("
            "theme TEXT PRIMARY KEY, "
            "status TEXT DEFAULT 'accumulating', "
            "count INTEGER DEFAULT 1, "
            "correction_dates TEXT, "
            "promoted_at TEXT)"
        )

        for entry in detected:
            theme_key = entry["msg"][:40].lower().strip()
            cursor.execute(
                "SELECT theme, count, correction_dates FROM correction_groups "
                "WHERE LOWER(SUBSTR(theme, 1, 40)) = ?",
                (theme_key,),
            )
            row = cursor.fetchone()
            if row:
                old_count = row[1]
                old_dates = json.loads(row[2]) if row[2] else []
                new_count = old_count + 1
                old_dates.append(entry["date"])
                new_status = "pending_promotion" if new_count >= 3 else "accumulating"
                cursor.execute(
                    "UPDATE correction_groups SET count = ?, correction_dates = ?, status = ? "
                    "WHERE theme = ?",
                    (new_count, json.dumps(old_dates), new_status, row[0]),
                )
            else:
                cursor.execute(
                    "INSERT INTO correction_groups (theme, status, count, correction_dates) "
                    "VALUES (?, 'accumulating', 1, ?)",
                    (entry["msg"][:300], json.dumps([entry["date"]])),
                )

        conn.commit()
        conn.close()
    except Exception:
        pass

if count_file:
    with open(count_file, "w") as f:
        f.write(str(len(detected)))
PYEOF
  [[ -f "$CORRECTION_COUNT_FILE" ]] && CORRECTION_COUNT=$(cat "$CORRECTION_COUNT_FILE") && rm -f "$CORRECTION_COUNT_FILE"
  CORRECTION_COUNT="${CORRECTION_COUNT:-0}"
fi

# ── Section 3: Signal processing ─────────────────────────────────────────────
DB_FILE="$HOME/.claude/.claude/epics.db"
if [[ -f "$DB_FILE" && -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  python3 "$HOME/.claude/hooks/lib/signal_processor.py" \
    "$TRANSCRIPT_PATH" "$DB_FILE" "${SESSION_ID_RAW:-}" 2>/dev/null || true
fi

# ── Section 4: Session summary via om_write ──────────────────────────────────
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
python3 - "$TRANSCRIPT_PATH" "$HOME/.claude" "${ARTIFACTS_CHANGED:-}" "${CORRECTION_COUNT:-0}" <<'SUMMEOF' 2>/dev/null || true
import json, os, sys
from datetime import datetime, timezone

transcript_path = sys.argv[1]
project_root = sys.argv[2]
artifacts = sys.argv[3] if len(sys.argv) > 3 else ""
correction_count = int(sys.argv[4]) if len(sys.argv) > 4 else 0

lines = []
try:
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
except Exception:
    sys.exit(0)

if not lines:
    sys.exit(0)

# Duration from timestamps
timestamps = []
for entry in lines:
    ts = entry.get("timestamp", "")
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            timestamps.append(dt.timestamp())
        except (ValueError, TypeError):
            try:
                timestamps.append(float(ts))
            except (ValueError, TypeError):
                continue

duration_min = int((max(timestamps) - min(timestamps)) / 60) if len(timestamps) >= 2 else 0
user_turns = sum(1 for e in lines if e.get("type") == "user")

# Only write if substantial
if user_turns <= 3 and duration_min <= 5:
    sys.exit(0)

# Dominant topic from edited file extensions
ext_counts = {}
for entry in lines:
    if entry.get("type") != "assistant":
        continue
    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        continue
    content = msg.get("content", [])
    if not isinstance(content, list):
        continue
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use" and block.get("name") in ("Edit", "Write"):
            fp = block.get("input", {}).get("file_path", "")
            if fp:
                ext = os.path.splitext(fp)[1] or os.path.basename(fp)
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

topic = max(ext_counts, key=ext_counts.get) if ext_counts else "general"
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
artifacts_str = artifacts if artifacts else "none"

summary = (
    f"Session {today}: {duration_min}min, {user_turns} turns, "
    f"{correction_count} corrections. Topic: {topic}. Artifacts: {artifacts_str}."
)

sys.path.insert(0, project_root)
from hooks.lib.om_write import om_write
om_write(content=summary, tags=["session-summary"], user_id="proj:dotclaude")
SUMMEOF
fi

# ── Section 5: Tool learning sync via om_write ───────────────────────────────
TOOL_LEARNINGS="$HOME/.claude/tool-learnings.md"
if [[ -f "$TOOL_LEARNINGS" ]]; then
python3 - "$TOOL_LEARNINGS" "$HOME/.claude" <<'TLEOF' 2>/dev/null || true
import os, re, sys
from datetime import datetime, timezone

tl_path = sys.argv[1]
project_root = sys.argv[2]
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

try:
    with open(tl_path) as f:
        content = f.read()
except Exception:
    sys.exit(0)

# Sync today's non-AUTO entries to OpenMemory
entries = []
for line in content.splitlines():
    line = line.strip()
    if not line.startswith("- ") or line.startswith("- AUTO:"):
        continue
    date_match = re.search(r'\d{4}-\d{2}-\d{2}', line)
    if date_match and date_match.group(0) == today:
        entries.append(line[2:].strip())

if not entries:
    sys.exit(0)

sys.path.insert(0, project_root)
from hooks.lib.om_write import om_write
for entry in entries:
    om_write(content=entry, tags=["tool-learning"], user_id="global")
TLEOF
fi

# ── Section 6: Auto-distillation for pending_promotion entries ────────────────
if [[ -f "$DB_FILE" ]]; then
python3 - "$DB_FILE" "$HOME/.claude" <<'DISTEOF' 2>/dev/null || true
import json, os, sqlite3, sys
from datetime import datetime, timezone

db_path = sys.argv[1]
project_root = sys.argv[2]
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
prefs_path = os.path.join(project_root, "behavioral-prefs.md")

conn = sqlite3.connect(db_path, timeout=10)
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='correction_groups'")
if not cursor.fetchone():
    conn.close()
    sys.exit(0)

cursor.execute(
    "SELECT rowid, theme, count, correction_dates FROM correction_groups "
    "WHERE status = 'pending_promotion'"
)
pending = cursor.fetchall()
if not pending:
    conn.close()
    sys.exit(0)

for rowid, theme, count, dates_json in pending:
    dates = json.loads(dates_json) if dates_json else []
    dates_str = ", ".join(dates[-3:])
    pref_text = (
        f"(auto-distilled) User corrected {count}x on: "
        f"{theme[:80]} ({dates_str}). Review and refine next session."
    )

    # Append to behavioral-prefs.md
    existing = ""
    if os.path.isfile(prefs_path):
        with open(prefs_path) as f:
            existing = f.read()
    with open(prefs_path, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(f"- {pref_text}\n")

    # Write to OpenMemory via om_write
    sys.path.insert(0, project_root)
    from hooks.lib.om_write import om_write
    om_write(content=pref_text, tags=["behavioral-pref"], user_id="proj:dotclaude")

    # Mark as promoted
    cursor.execute(
        "UPDATE correction_groups SET status = 'promoted', promoted_at = ? WHERE rowid = ?",
        (today, rowid),
    )

conn.commit()
conn.close()
DISTEOF
fi

# Cleanup
SESSION_START_FILE="/tmp/session-start-${SESSION_ID}"
rm -f "$SESSION_START_FILE"

exit 0
