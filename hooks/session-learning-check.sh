#!/bin/bash
# Stop hook — transcript-based session learning.
# Reads transcript JSONL from stdin, writes idempotent session records.
# Also checks behavioral file mtimes (legacy functionality preserved).

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

# --- Legacy: behavioral file mtime checks ---
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
SNAPSHOT="/tmp/session-mtimes-${SESSION_ID}"

if [[ -f "$SNAPSHOT" ]]; then
  source "$SNAPSHOT"

  if stat -f %m / >/dev/null 2>&1; then
    mtime() { stat -f %m "$1" 2>/dev/null || echo "0"; }
  elif stat -c %Y / >/dev/null 2>&1; then
    mtime() { stat -c %Y "$1" 2>/dev/null || echo "0"; }
  else
    mtime() { python3 -c "import os; print(int(os.path.getmtime('$1')))" 2>/dev/null || echo "0"; }
  fi

  CURRENT_DISAGREE=$(mtime "$HOME/.claude/disagreements.md")
  CURRENT_OUTCOMES=$(mtime "$HOME/.claude/outcomes.md")
  CURRENT_CORRECTIONS=$(mtime "$HOME/.claude/corrections.md")
  CURRENT_FRICTION=$(mtime "$HOME/.claude/friction-log.md")
  CURRENT_HANDOFF=$(mtime "$HOME/.claude/session-handoff.md")

  DISAGREE_CHANGED=false
  OUTCOMES_CHANGED=false
  [[ "$CURRENT_DISAGREE" != "${DISAGREE_MTIME:-0}" ]] && DISAGREE_CHANGED=true
  [[ "$CURRENT_OUTCOMES" != "${OUTCOMES_MTIME:-0}" ]] && OUTCOMES_CHANGED=true

  # Track which artifacts changed (for session record)
  ARTIFACTS_CHANGED=""
  [[ "$DISAGREE_CHANGED" == true ]] && ARTIFACTS_CHANGED="disagreements"
  [[ "$OUTCOMES_CHANGED" == true ]] && ARTIFACTS_CHANGED="${ARTIFACTS_CHANGED:+$ARTIFACTS_CHANGED, }outcomes"
  [[ "$CURRENT_CORRECTIONS" != "${CORRECTIONS_MTIME:-0}" ]] && ARTIFACTS_CHANGED="${ARTIFACTS_CHANGED:+$ARTIFACTS_CHANGED, }corrections"
  [[ "$CURRENT_FRICTION" != "${FRICTION_MTIME:-0}" ]] && ARTIFACTS_CHANGED="${ARTIFACTS_CHANGED:+$ARTIFACTS_CHANGED, }friction-log"
  [[ "$CURRENT_HANDOFF" != "${HANDOFF_MTIME:-0}" ]] && ARTIFACTS_CHANGED="${ARTIFACTS_CHANGED:+$ARTIFACTS_CHANGED, }session-handoff"

  if [[ "$DISAGREE_CHANGED" == true && "$OUTCOMES_CHANGED" == false ]]; then
    echo "disagreements.md modified — outcomes.md unchanged"
    echo "→ Log an outcome for this session's disagreement(s) next session."
  elif [[ "$DISAGREE_CHANGED" == true && "$OUTCOMES_CHANGED" == true ]]; then
    echo "disagreements.md + outcomes.md both updated"
    echo "→ Distillation will trigger at threshold."
  elif [[ "$OUTCOMES_CHANGED" == true ]]; then
    echo "outcomes.md updated → distillation will trigger at threshold."
  fi

  rm -f "$SNAPSHOT"
fi

# --- Transcript analysis ---
if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
  exit 0
fi

python3 - "$TRANSCRIPT_PATH" "$HOME/.claude" "${ARTIFACTS_CHANGED:-}" "${SESSION_ID_RAW:-}" <<'PYEOF'
import json, os, re, sys, time
from datetime import datetime, timezone

transcript_path = sys.argv[1]
project_root = sys.argv[2]
artifacts_changed = sys.argv[3] if len(sys.argv) > 3 else ""
session_id = sys.argv[4] if len(sys.argv) > 4 else ""

records_file = os.path.join(project_root, "session-records.md")

# --- Parse transcript ---
lines = []
try:
    with open(transcript_path, "r") as f:
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

# Truncate to last 2000 lines if too large
if len(lines) > 5000:
    lines = lines[-2000:]

# Extract turns: (role, content, timestamp)
turns = []
for entry in lines:
    role = entry.get("type", "")
    ts = entry.get("timestamp", "")
    content = ""

    if role == "user":
        msg = entry.get("message", "")
        if isinstance(msg, str):
            content = msg
        elif isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
        elif isinstance(msg, list):
            content = " ".join(
                p.get("text", "") for p in msg
                if isinstance(p, dict) and p.get("type") == "text"
            )
    elif role == "assistant":
        msg = entry.get("message", "")
        if isinstance(msg, str):
            content = msg
        elif isinstance(msg, dict):
            c = msg.get("content", "")
            if isinstance(c, str):
                content = c
            elif isinstance(c, list):
                content = " ".join(
                    p.get("text", "") for p in c
                    if isinstance(p, dict) and p.get("type") == "text"
                )
    else:
        continue

    if content:
        turns.append({"role": role, "content": content.strip(), "ts": ts})

if not turns:
    sys.exit(0)

# --- Cluster detection: 3+ short user turns (<50 chars) in sequence ---
clusters = 0
cluster_start = None
cluster_count = 0
for i, turn in enumerate(turns):
    if turn["role"] == "user" and len(turn["content"]) < 50:
        if cluster_start is None:
            cluster_start = i
        cluster_count += 1
    else:
        if cluster_count >= 3:
            clusters += 1
        cluster_start = None
        cluster_count = 0

# Check trailing cluster
if cluster_count >= 3:
    clusters += 1

# --- Extract metadata from transcript ---
# Scan for file edits (Edit/Write tool calls)
edited_files = set()
edit_count = 0
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
            inp = block.get("input", {})
            fp = inp.get("file_path", "")
            if fp:
                edited_files.add(os.path.basename(fp))
                edit_count += 1

# --- Compute session duration and turn count ---
user_turns = [t for t in turns if t["role"] == "user"]
total_turns = len(user_turns)

# Try to get duration from timestamps
duration_min = 0
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

if len(timestamps) >= 2:
    duration_min = int((max(timestamps) - min(timestamps)) / 60)

# --- Write session record (idempotent) ---
# Only write if substantial: duration > 5 min AND (turns > 3 OR edits > 5)
if duration_min > 5 and (total_turns > 3 or edit_count > 5):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    # Key exchanges: substantive user messages (>20 chars, not just "yes"/"ok")
    # Skip [Request interrupted...], truncate to first line, limit to 3
    key_exchanges = []
    for t in user_turns:
        msg = t["content"].strip()
        if msg.startswith("[Request interrupted"):
            continue
        # Take first line only
        first_line = msg.split("\n")[0].replace("\r", "")
        if (len(first_line) > 20
            and first_line.lower() not in ("yes", "ok", "okay", "sure", "thanks", "thank you", "y", "n")):
            key_exchanges.append(first_line[:100])
        if len(key_exchanges) >= 3:
            break

    files_str = ", ".join(sorted(edited_files)[:15]) if edited_files else "(none)"
    artifacts_str = artifacts_changed if artifacts_changed else "none"

    # Build the record block
    marker = f"<!-- session: {session_id} -->" if session_id else ""
    record_lines = []
    if marker:
        record_lines.append(marker)
    record_lines.append(f"## {now_iso} — {duration_min}min — {total_turns} turns — {edit_count} edits")
    record_lines.append(f"Files: {files_str}")
    if clusters > 0:
        record_lines.append(f"Friction clusters: {clusters}")
    if key_exchanges:
        record_lines.append("Key exchanges:")
        for ke in key_exchanges:
            record_lines.append(f"  - \"{ke}\"")
    record_lines.append(f"Artifacts updated: {artifacts_str}")
    record_block = "\n".join(record_lines)

    # Idempotent upsert: if session_id marker exists, replace that block
    existing = ""
    if os.path.isfile(records_file):
        try:
            with open(records_file) as f:
                existing = f.read()
        except Exception:
            existing = ""

    if marker and marker in existing:
        # Replace existing block: from marker to next marker or next ## or end
        pattern = re.escape(marker) + r'\n.*?(?=\n<!-- session: |\n## \d{4}-\d{2}-\d{2}|\Z)'
        new_content = re.sub(pattern, record_block, existing, count=1, flags=re.DOTALL)
        with open(records_file, "w") as f:
            f.write(new_content)
    else:
        # Append
        with open(records_file, "a") as f:
            f.write(f"\n{record_block}\n")

    # Substance warning: substantial session + zero artifacts + zero clusters
    if not artifacts_changed and clusters == 0:
        print(f"Session: {total_turns} turns over {duration_min} minutes. No friction clusters, no artifacts updated.")

PYEOF

# --- Correction tally extraction ---
python3 - "$TRANSCRIPT_PATH" "$HOME/.claude" "${SESSION_ID_RAW:-}" "${CORRECTIONS_MTIME:-0}" <<'TALLYEOF'
import json, os, re, sys, time
from datetime import datetime, timezone

transcript_path = sys.argv[1]
project_root = sys.argv[2]
session_id = sys.argv[3] if len(sys.argv) > 3 else ""
corrections_mtime_start = sys.argv[4] if len(sys.argv) > 4 else "0"

tallies_file = os.path.join(project_root, "correction-tallies.jsonl")
corrections_file = os.path.join(project_root, "corrections.md")
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Load existing tallies for dedup
# Structural: dedup by (session_id, msg[:50]) — same msg in different sessions is valid
# Manual: dedup by msg[:50] alone — corrections.md entries are session-independent
existing_structural = set()
existing_manual = set()
if os.path.isfile(tallies_file):
    try:
        with open(tallies_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    msg_key = entry.get("user_msg", "")[:50]
                    if entry.get("source") == "manual":
                        existing_manual.add(msg_key)
                    else:
                        existing_structural.add((entry.get("session_id", ""), msg_key))
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

new_tallies = []

# --- Parse transcript for structural detection ---
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
    lines = []

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

# Pattern 1: Imperative redirect — user msg <150 chars starting with imperative verb
#   after assistant output containing tool_use
IMPERATIVE_STARTS = re.compile(
    r'^(use |stop |don\'t |do not |just |why didn\'t |why don\'t |why aren\'t |'
    r'make |run |try |ship |log |fix |check |read |write |call |add |remove |'
    r'never |always )',
    re.IGNORECASE
)

# Pattern 2: Frustration — 2+ ALL-CAPS words or ends with !! or ??
def is_frustration(msg):
    if msg.rstrip().endswith("!!") or msg.rstrip().endswith("??"):
        return True
    caps_words = [w for w in msg.split() if w.isupper() and len(w) > 1]
    return len(caps_words) >= 2

# Pattern 3: Meta-comment about Claude's behavior
META_PATTERN = re.compile(
    r"you'?ve been |you'?re not |you keep |you should |you always |you never ",
    re.IGNORECASE
)

# Skip system-generated messages (XML tags, skill expansions, task notifications)
SYSTEM_MSG = re.compile(
    r'<(local-command-caveat|task-notification|system-reminder|command-name|command-message)>|'
    r'^Base directory for this skill|'
    r'^Implement the following plan:|'
    r'^<skill-',
    re.IGNORECASE
)

prev_assistant_had_tool_use = False
for i, turn in enumerate(turns):
    if turn["role"] == "assistant":
        prev_assistant_had_tool_use = turn["has_tool_use"]
        continue

    if turn["role"] != "user":
        continue

    msg = turn["content"]

    # Skip system-generated content
    if SYSTEM_MSG.search(msg):
        prev_assistant_had_tool_use = False
        continue

    matched = False

    # Pattern 1: imperative redirect after tool_use
    if (len(msg) < 150 and prev_assistant_had_tool_use
            and IMPERATIVE_STARTS.match(msg)):
        matched = True

    # Pattern 2: frustration signal
    if not matched and is_frustration(msg):
        matched = True

    # Pattern 3: meta-comment
    if not matched and META_PATTERN.search(msg):
        matched = True

    if matched:
        struct_key = (session_id, msg[:50])
        if struct_key not in existing_structural:
            new_tallies.append({
                "user_msg": msg[:300],
                "date": today,
                "session_id": session_id,
                "source": "structural",
                "promoted": False,
            })
            existing_structural.add(struct_key)

    prev_assistant_had_tool_use = False

# --- Manual correction tallying ---
# If corrections.md mtime changed during this session, scan for today's entries
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
            # Find entries with today's date
            for match in re.finditer(r'^## (\d{4}-\d{2}-\d{2}) — (.+)', content, re.MULTILINE):
                entry_date = match.group(1)
                entry_desc = match.group(2).strip()
                if entry_date == today:
                    manual_key = entry_desc[:50]
                    if manual_key not in existing_manual:
                        new_tallies.append({
                            "user_msg": entry_desc[:300],
                            "date": today,
                            "session_id": session_id,
                            "source": "manual",
                            "promoted": False,
                        })
                        existing_manual.add(manual_key)
        except Exception:
            pass

# Write new tallies
if new_tallies:
    try:
        with open(tallies_file, "a") as f:
            for tally in new_tallies:
                f.write(json.dumps(tally) + "\n")
    except Exception:
        pass

TALLYEOF

# --- Dual-write to OpenMemory: corrections and outcomes ---
OM_DB="$HOME/.claude/.claude/openmemory.sqlite"
if [[ -f "$OM_DB" && -f "$SNAPSHOT" ]] || [[ -f "$OM_DB" ]]; then
python3 - "$HOME/.claude" "$OM_DB" "${CORRECTIONS_MTIME:-0}" "${OUTCOMES_MTIME:-0}" <<'OMWRITEEOF'
import hashlib, json, os, re, subprocess, sys, time, uuid
from datetime import datetime, timezone

project_root = sys.argv[1]
om_db = sys.argv[2]
corrections_mtime_start = int(sys.argv[3]) if len(sys.argv) > 3 else 0
outcomes_mtime_start = int(sys.argv[4]) if len(sys.argv) > 4 else 0

now_ts = int(time.time())
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

def get_mtime(path):
    try:
        return int(os.path.getmtime(path))
    except Exception:
        return 0

def om_insert(content, tags, user_id="proj:dotclaude", sector="procedural"):
    """Direct SQL INSERT into OpenMemory — no embedding (mean_vec=NULL)."""
    mem_id = str(uuid.uuid4())
    tags_json = json.dumps(tags)
    # Use simhash for dedup: hash of content
    simhash = hashlib.md5(content.encode()).hexdigest()[:16]
    try:
        subprocess.run(
            ["sqlite3", om_db,
             f"INSERT OR IGNORE INTO memories "
             f"(id, user_id, content, simhash, primary_sector, tags, created_at, updated_at, last_seen_at, salience, decay_lambda, feedback_score) "
             f"VALUES ('{mem_id}', '{user_id}', '{content.replace(chr(39), chr(39)+chr(39))}', '{simhash}', "
             f"'{sector}', '{tags_json.replace(chr(39), chr(39)+chr(39))}', {now_ts}, {now_ts}, {now_ts}, 0.5, 0.05, 0);"],
            capture_output=True, text=True, timeout=5
        )
    except Exception:
        pass

def check_existing(simhash):
    """Check if a memory with this simhash already exists."""
    try:
        r = subprocess.run(
            ["sqlite3", om_db, f"SELECT COUNT(*) FROM memories WHERE simhash='{simhash}';"],
            capture_output=True, text=True, timeout=5
        )
        return int(r.stdout.strip()) > 0
    except Exception:
        return False

# Process new corrections
corrections_file = os.path.join(project_root, "corrections.md")
if os.path.isfile(corrections_file) and get_mtime(corrections_file) > corrections_mtime_start:
    try:
        with open(corrections_file) as f:
            content = f.read()
        # Find entries with today's date
        for match in re.finditer(r'^## (\d{4}-\d{2}-\d{2}) — (.+?)(?=\n## |\Z)', content, re.MULTILINE | re.DOTALL):
            entry_date = match.group(1)
            entry_body = match.group(0).strip()
            if entry_date == today:
                simhash = hashlib.md5(entry_body.encode()).hexdigest()[:16]
                if not check_existing(simhash):
                    # Extract the user_said line for a concise memory
                    user_said = ""
                    for line in entry_body.splitlines():
                        if line.startswith("**User said**:"):
                            user_said = line.split(":", 1)[1].strip()[:200]
                            break
                    mem_content = user_said if user_said else entry_body[:200]
                    om_insert(mem_content, ["correction", "behavioral"], sector="procedural")
    except Exception:
        pass

# Process new outcomes
outcomes_file = os.path.join(project_root, "outcomes.md")
if os.path.isfile(outcomes_file) and get_mtime(outcomes_file) > outcomes_mtime_start:
    try:
        with open(outcomes_file) as f:
            content = f.read()
        for match in re.finditer(r'^## (\d{4}-\d{2}-\d{2}) — (.+?)(?=\n## |\Z)', content, re.MULTILINE | re.DOTALL):
            entry_date = match.group(1)
            entry_body = match.group(0).strip()
            if entry_date == today:
                simhash = hashlib.md5(entry_body.encode()).hexdigest()[:16]
                if not check_existing(simhash):
                    om_insert(entry_body[:300], ["outcome", "behavioral"], sector="procedural")
    except Exception:
        pass

OMWRITEEOF
fi

# Transcript embedding (background, non-blocking)
if [[ -f "$OM_DB" && -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  python3 "$HOME/.claude/hooks/lib/transcript_embedder.py" "$TRANSCRIPT_PATH" "$OM_DB" &
fi

# Cleanup session start timestamp
SESSION_START_FILE="/tmp/session-start-${SESSION_ID}"
rm -f "$SESSION_START_FILE"

exit 0
