#!/bin/bash
# Stop hook — session learning extraction.
# Reads transcript JSONL from stdin, detects corrections, syncs learnings.

source "$(dirname "$0")/lib/profile.sh"
require_profile 1

# Read stdin for transcript_path and session metadata
INPUT=$(cat)

TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('transcript_path', ''))
" 2>/dev/null)

SESSION_ID_RAW=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('session_id', ''))
" 2>/dev/null)

CWD=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('cwd', ''))
" 2>/dev/null)

# ============================================================
# Section 1: Mtime comparison
# ============================================================
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
SNAPSHOT="/tmp/session-mtimes-${SESSION_ID}"

CORRECTIONS_CHANGED=false
OUTCOMES_CHANGED=false

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
  CURRENT_BEHAVPREFS=$(mtime "$HOME/.claude/behavioral-prefs.md")

  [[ "$CURRENT_CORRECTIONS" != "${CORRECTIONS_MTIME:-0}" ]] && CORRECTIONS_CHANGED=true
  [[ "$CURRENT_OUTCOMES" != "${OUTCOMES_MTIME:-0}" ]] && OUTCOMES_CHANGED=true

  if [[ "$CORRECTIONS_CHANGED" == true && "$OUTCOMES_CHANGED" == false ]]; then
    echo "corrections.md modified — outcomes.md unchanged"
  elif [[ "$CORRECTIONS_CHANGED" == true && "$OUTCOMES_CHANGED" == true ]]; then
    echo "corrections.md + outcomes.md both updated"
  elif [[ "$OUTCOMES_CHANGED" == true ]]; then
    echo "outcomes.md updated"
  fi

  rm -f "$SNAPSHOT"
fi

# Exit early if no transcript
if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
  exit 0
fi

# ============================================================
# Section 2: Correction detection → correction_groups
# ============================================================
DB_FILE="$HOME/.claude/.claude/epics.db"

python3 - "$TRANSCRIPT_PATH" "$DB_FILE" "${SESSION_ID_RAW:-}" "$HOME/.claude" <<'CORREOF'
import sys, os
transcript_path = sys.argv[1]
db_file = sys.argv[2]
session_id = sys.argv[3] if len(sys.argv) > 3 else ""
project_root = sys.argv[4]
sys.path.insert(0, project_root)
from hooks.lib.signal_processor import process_session_corrections
process_session_corrections(transcript_path, db_file, session_id, project_root)
CORREOF

# ============================================================
# Section 3: Signal processing
# ============================================================
if [[ -f "$DB_FILE" && -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  python3 "$HOME/.claude/hooks/lib/signal_processor.py" \
    "$TRANSCRIPT_PATH" "$DB_FILE" "${SESSION_ID_RAW:-}" 2>/dev/null || true
fi

# ============================================================
# Section 4: Session summary via om_write
# ============================================================
python3 - "$TRANSCRIPT_PATH" "$HOME/.claude" <<'SUMMARYEOF'
import json, os, sys
from datetime import datetime

transcript_path = sys.argv[1]
project_root = sys.argv[2]

lines = []
try:
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except:
                    continue
except:
    sys.exit(0)

user_turns = sum(1 for e in lines if e.get("type") == "user")
if user_turns < 3:
    sys.exit(0)

timestamps = []
for entry in lines:
    ts = entry.get("timestamp", "")
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            timestamps.append(dt.timestamp())
        except:
            continue

duration_min = int((max(timestamps) - min(timestamps)) / 60) if len(timestamps) >= 2 else 0
if duration_min < 5:
    sys.exit(0)

edited_files = set()
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
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in ("Edit", "Write"):
            fp = block.get("input", {}).get("file_path", "")
            if fp:
                edited_files.add(os.path.basename(fp))

topic = ", ".join(sorted(edited_files)[:5]) if edited_files else "discussion"
today = datetime.now().strftime("%Y-%m-%d")

sys.path.insert(0, project_root)
try:
    from hooks.lib.om_write import om_write
    om_write(
        content=f"Session {today}: {duration_min}min, {user_turns} turns. Topic: {topic}.",
        tags=["session-summary"],
        user_id="proj:dotclaude"
    )
except Exception:
    pass
SUMMARYEOF

# ============================================================
# Section 5: Tool learning sync via om_write
# ============================================================
python3 - "$HOME/.claude" <<'LEARNEOF'
import os, sys

project_root = sys.argv[1]
learnings_file = os.path.join(project_root, "tool-learnings.md")
if not os.path.isfile(learnings_file):
    sys.exit(0)

with open(learnings_file) as f:
    content = f.read()

entries = []
for line in content.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("<!--"):
        continue
    if line.startswith("- "):
        text = line[2:].strip()
        if not text.startswith("AUTO:"):
            entries.append(text)

if not entries:
    sys.exit(0)

sys.path.insert(0, project_root)
try:
    from hooks.lib.om_write import om_write
    for entry in entries:
        om_write(content=entry, tags=["tool-learning"], user_id="global")
except Exception:
    pass
LEARNEOF

# ============================================================
# Section 6: Auto-distillation for pending_promotion entries
# ============================================================
if [[ -f "$DB_FILE" ]]; then
python3 - "$DB_FILE" "$HOME/.claude" <<'DISTILLEOF'
import os, sqlite3, sys
from datetime import datetime

db_file = sys.argv[1]
project_root = sys.argv[2]
prefs_file = os.path.join(project_root, "behavioral-prefs.md")
today = datetime.now().strftime("%Y-%m-%d")

try:
    conn = sqlite3.connect(db_file, timeout=5)
    rows = conn.execute(
        "SELECT theme, count, correction_dates FROM correction_groups WHERE status='pending_promotion'"
    ).fetchall()
except Exception:
    sys.exit(0)

if not rows:
    conn.close()
    sys.exit(0)

sys.path.insert(0, project_root)

# Read existing prefs file to check for duplicates
existing_content = ""
try:
    with open(prefs_file) as f:
        existing_content = f.read()
except Exception:
    pass

for theme, count, dates in rows:
    pref_text = f"(auto-distilled) User corrected {count}x on: {theme[:200]} ({dates}). Review and refine next session."

    try:
        with open(prefs_file, "r") as f:
            content = f.read()
        theme_key = theme[:40].lower()
        lines = content.split('\n')
        replaced = False
        for idx, line in enumerate(lines):
            if '(auto-distilled)' in line and theme_key in line.lower():
                lines[idx] = f"- {pref_text}"
                replaced = True
                break
        if replaced:
            with open(prefs_file, "w") as f:
                f.write('\n'.join(lines))
        else:
            with open(prefs_file, "a") as f:
                f.write(f"\n- {pref_text}\n")
    except Exception:
        pass

    try:
        from hooks.lib.om_write import om_write
        om_write(content=pref_text, tags=["behavioral-pref"], user_id="proj:dotclaude")
    except Exception:
        pass

    try:
        conn.execute(
            "UPDATE correction_groups SET status='promoted', promoted_at=?, text=? WHERE theme=?",
            (today, pref_text, theme)
        )
        conn.commit()
    except Exception:
        pass

# Cleanup: mark pending_promotion rows as promoted if already present in behavioral-prefs.md
try:
    with open(prefs_file, "r") as f:
        prefs_content = f.read().lower()
    remaining = conn.execute(
        "SELECT theme FROM correction_groups WHERE status='pending_promotion'"
    ).fetchall()
    for (rtheme,) in remaining:
        if '(auto-distilled)' in prefs_content and rtheme[:40].lower() in prefs_content:
            conn.execute(
                "UPDATE correction_groups SET status='promoted', promoted_at=? WHERE theme=?",
                (today, rtheme)
            )
    conn.commit()
except Exception:
    pass

conn.close()
DISTILLEOF
fi

# ============================================================
# Section 6b: Compliance hook generation for newly promoted prefs
# ============================================================
# Skip hook generation in subagent sessions
if [[ -n "${CLAUDE_AGENT_ID:-}" ]]; then
  :
elif [[ -f "$DB_FILE" ]]; then
python3 - "$DB_FILE" "$HOME/.claude" <<'HOOKGENEOF'
import json, os, sqlite3, sys

db_file = sys.argv[1]
project_root = sys.argv[2]

try:
    conn = sqlite3.connect(db_file, timeout=5)
    schema_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='correction_groups'"
    ).fetchone()
    if schema_sql and "'dismissed'" not in schema_sql[0]:
        conn.executescript("""
            ALTER TABLE correction_groups RENAME TO correction_groups_old;
            CREATE TABLE correction_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                theme TEXT NOT NULL,
                status TEXT DEFAULT 'accumulating' CHECK(status IN ('accumulating','pending_promotion','promoted','dismissed')),
                count INTEGER DEFAULT 1,
                correction_dates TEXT DEFAULT '[]',
                embedding BLOB,
                promoted_at TEXT,
                created_at INTEGER,
                updated_at INTEGER
            );
            INSERT INTO correction_groups SELECT * FROM correction_groups_old;
            DROP TABLE correction_groups_old;
            CREATE INDEX IF NOT EXISTS idx_correction_groups_status ON correction_groups(status);
        """)
    rows = conn.execute(
        "SELECT theme FROM correction_groups WHERE status='promoted' AND date(promoted_at) = date('now', 'localtime')"
    ).fetchall()
    conn.close()
except Exception:
    sys.exit(0)

if not rows:
    sys.exit(0)

sys.path.insert(0, project_root)
try:
    from hooks.lib.hook_generator import generate_hook
except ImportError:
    sys.exit(0)

for (theme,) in rows:
    try:
        result = generate_hook(theme, project_root=project_root, db_file=db_file)
        if result is None:
            print(f"Hook eval: not hookable: {theme[:80]}", file=sys.stderr)
        elif result.get("skipped"):
            pass
        else:
            print(f"Hook generated: {result['path']}", file=sys.stderr)
    except Exception as e:
        print(f"Hook generation failed for {theme[:80]}: {e}", file=sys.stderr)
HOOKGENEOF
fi

# Cleanup
SESSION_START_FILE="/tmp/session-start-${SESSION_ID}"
rm -f "$SESSION_START_FILE"

exit 0
