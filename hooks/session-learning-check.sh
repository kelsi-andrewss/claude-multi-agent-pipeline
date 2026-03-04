#!/bin/bash
# Stop hook — transcript-based session learning.
# Reads transcript JSONL from stdin, detects corrections, writes session records.
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

# --- Transcript analysis (new) ---
if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
  exit 0
fi

python3 - "$TRANSCRIPT_PATH" "$HOME/.claude" "${ARTIFACTS_CHANGED:-}" <<'PYEOF'
import json, os, re, sys, time
from datetime import datetime, timezone

transcript_path = sys.argv[1]
project_root = sys.argv[2]
artifacts_changed = sys.argv[3] if len(sys.argv) > 3 else ""

corrections_file = os.path.join(project_root, "corrections.md")
records_file = os.path.join(project_root, "session-records.md")
memory_queue = os.path.join(project_root, "memory-queue.md")

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
        # User messages: content is typically a string or list
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

# --- Detect corrections ---
CORRECTION_PATTERNS = [
    r'(?i)^no[,.\s]',
    r'(?i)^that\'?s not',
    r'(?i)^wrong',
    r'(?i)^actually[,\s]',
    r'(?i)not what i (meant|asked|want)',
    r'(?i)^stop[,.\s]',
    r'(?i)^i (meant|want|need)\s',
    r'(?i)that\'?s wrong',
    r'(?i)to clarify[,:\s]',
    r'(?i)i should have said',
]

FALSE_POSITIVE_PREFIXES = [
    "no problem", "no worries", "no need", "no thanks", "no thank you",
    "no rush", "no pressure", "no biggie", "no issue", "no change",
    "actually, that", "actually that", "actually yeah", "actually yes",
    "actually it", "actually looks", "actually works", "actually good",
    "actually perfect", "actually great", "actually nice",
]

corrections = []
for i, turn in enumerate(turns):
    if turn["role"] != "user":
        continue
    msg = turn["content"]

    # Only flag if previous turn was assistant (not multi-line user input)
    if i > 0 and turns[i - 1]["role"] != "assistant":
        continue

    for pattern in CORRECTION_PATTERNS:
        if re.search(pattern, msg):
            # Filter out known false positives
            msg_lower = msg.lower()
            if any(msg_lower.startswith(fp) for fp in FALSE_POSITIVE_PREFIXES):
                break
            prev_content = turns[i - 1]["content"] if i > 0 else ""
            corrections.append({
                "user_msg": msg[:300],
                "prev_context": prev_content[-100:] if prev_content else "",
                "turn": i,
                "type": "AUTO",
            })
            break

# Cluster detection: 3+ short user turns (<50 chars) in sequence
cluster_start = None
cluster_count = 0
for i, turn in enumerate(turns):
    if turn["role"] == "user" and len(turn["content"]) < 50:
        if cluster_start is None:
            cluster_start = i
        cluster_count += 1
    else:
        if cluster_count >= 3:
            # Flag the cluster
            cluster_msgs = [
                turns[j]["content"][:80]
                for j in range(cluster_start, cluster_start + cluster_count)
                if j < len(turns) and turns[j]["role"] == "user"
            ]
            corrections.append({
                "user_msg": " / ".join(cluster_msgs[:3]),
                "prev_context": "cluster of short user turns suggesting friction",
                "turn": cluster_start,
                "type": "AUTO-CLUSTER",
            })
        cluster_start = None
        cluster_count = 0

# Check trailing cluster
if cluster_count >= 3 and cluster_start is not None:
    cluster_msgs = [
        turns[j]["content"][:80]
        for j in range(cluster_start, cluster_start + cluster_count)
        if j < len(turns) and turns[j]["role"] == "user"
    ]
    corrections.append({
        "user_msg": " / ".join(cluster_msgs[:3]),
        "prev_context": "cluster of short user turns suggesting friction",
        "turn": cluster_start,
        "type": "AUTO-CLUSTER",
    })

# --- Detect preferences, decisions, and facts from user turns ---
PREFERENCE_PATTERNS = [
    r'(?i)i prefer\s',
    r'(?i)always use\s',
    r'(?i)never do\s',
    r'(?i)i like\s',
    r'(?i)i want you to\s',
    r'(?i)from now on[,\s]',
    r'(?i)remember that\s',
]

DECISION_PATTERNS = [
    r"(?i)let'?s use\s",
    r'(?i)we decided\s',
    r'(?i)the approach is\s',
    r"(?i)we'?ll go with\s",
    r'(?i)^decision:\s',
]

FACT_PATTERNS = [
    r'(?i)i work on\s',
    r'(?i)my project uses\s',
    r'(?i)the codebase is\s',
    r"(?i)i'?m building\s",
    r'(?i)my stack is\s',
]

# Set of turn indices already flagged as corrections (skip those)
correction_turn_indices = {c["turn"] for c in corrections}

extractions = []
project_name = os.path.basename(os.getcwd())

for i, turn in enumerate(turns):
    if turn["role"] != "user":
        continue
    if i in correction_turn_indices:
        continue
    if len(extractions) >= 5:
        break

    msg = turn["content"]
    tag = None

    for pattern in PREFERENCE_PATTERNS:
        if re.search(pattern, msg):
            tag = "preference"
            break

    if tag is None:
        for pattern in DECISION_PATTERNS:
            if re.search(pattern, msg):
                tag = "decision"
                break

    if tag is None:
        for pattern in FACT_PATTERNS:
            if re.search(pattern, msg):
                tag = "fact"
                break

    if tag is not None:
        extractions.append({"content": msg[:200], "tag": tag})

# Deduplicate against existing memory-queue entries
existing_queue_prefixes = set()
try:
    with open(memory_queue, "r") as f:
        for line in f:
            if line.startswith("content:"):
                existing_queue_prefixes.add(line[8:].strip()[:50])
except Exception:
    pass

unique_extractions = []
for ex in extractions:
    prefix = ex["content"][:50]
    if prefix not in existing_queue_prefixes:
        unique_extractions.append(ex)
        existing_queue_prefixes.add(prefix)

# --- Write corrections ---
now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
if corrections:
    with open(corrections_file, "a") as f:
        for c in corrections:
            label = c["user_msg"][:80]
            f.write(f"\n## {now_iso} — {c['type']}: {label}\n")
            f.write(f"**Context**: {c['prev_context']}\n")
            f.write(f"**User said**: {c['user_msg']}\n")
            f.write(f"**Turn**: {c['turn']}\n")

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
            # Try ISO format
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            timestamps.append(dt.timestamp())
        except (ValueError, TypeError):
            try:
                timestamps.append(float(ts))
            except (ValueError, TypeError):
                continue

if len(timestamps) >= 2:
    duration_min = int((max(timestamps) - min(timestamps)) / 60)

# --- Write session record ---
# Only write if substantial: duration > 5 min AND (turns > 3 OR edits > 5)
if duration_min > 5 and (total_turns > 3 or edit_count > 5):
    # Key exchanges: substantive user messages (>20 chars, not just "yes"/"ok")
    key_exchanges = []
    for t in user_turns:
        msg = t["content"].strip().replace("\n", " ").replace("\r", "")
        if (len(msg) > 20
            and msg.lower() not in ("yes", "ok", "okay", "sure", "thanks", "thank you", "y", "n")
            and not msg.startswith("[Request interrupted")):
            key_exchanges.append(msg[:100])
        if len(key_exchanges) >= 5:
            break

    files_str = ", ".join(sorted(edited_files)[:15]) if edited_files else "(none)"
    artifacts_str = artifacts_changed if artifacts_changed else "none"

    with open(records_file, "a") as f:
        f.write(f"\n## {now_iso} — {duration_min}min — {total_turns} turns — {edit_count} edits\n")
        f.write(f"Files: {files_str}\n")
        f.write(f"Corrections detected: {len(corrections)}\n")
        if key_exchanges:
            f.write("Key exchanges:\n")
            for ke in key_exchanges:
                f.write(f"  - \"{ke}\"\n")
        f.write(f"Artifacts updated: {artifacts_str}\n")

    # Substance warning: substantial session + zero artifacts + zero corrections
    if not artifacts_changed and not corrections:
        print(f"Session: {total_turns} turns over {duration_min} minutes. No corrections detected, no artifacts updated.")

# --- Queue corrections for OpenMemory drain ---
if corrections:
    try:
        with open(memory_queue, "a") as f:
            for c in corrections:
                f.write(f"\n- openmemory_store(content=\"{c['type']} correction: {c['user_msg'][:100]}\", tags=[\"correction\"], user_id=\"proj:dotclaude\")\n")
    except Exception:
        pass

# --- Queue extracted learnings for OpenMemory drain ---
if unique_extractions:
    try:
        with open(memory_queue, "a") as f:
            for ex in unique_extractions:
                tag = ex["tag"]
                user_id = "proj:" + project_name if tag == "decision" else "global"
                f.write(f"\n## {now_iso}\n")
                f.write(f"content: {ex['content']}\n")
                f.write(f"tags: {tag}\n")
                f.write(f"user_id: {user_id}\n")
                f.write(f"sector: procedural\n")
    except Exception:
        pass

# --- Queue session summary for OpenMemory drain ---
if duration_min > 5 and (total_turns > 3 or edit_count > 5):
    # Determine session shape
    if edit_count > total_turns:
        shape = "building"
    elif len(corrections) > 0:
        shape = "debugging"
    else:
        shape = "discussing"

    # Build key topics from first 2 key exchanges
    key_topics = []
    for t in user_turns:
        msg = t["content"].strip().replace("\n", " ").replace("\r", "")
        if (len(msg) > 20
            and msg.lower() not in ("yes", "ok", "okay", "sure", "thanks", "thank you", "y", "n")
            and not msg.startswith("[Request interrupted")):
            key_topics.append(msg[:60])
        if len(key_topics) >= 2:
            break
    topics_str = "; ".join(key_topics) if key_topics else "general work"

    summary_content = (
        f"Session {now_iso}: {shape}. {duration_min}min, {total_turns} turns, "
        f"{edit_count} edits. Key topics: {topics_str}. Corrections: {len(corrections)}."
    )

    try:
        with open(memory_queue, "a") as f:
            f.write(f"\n## {now_iso}\n")
            f.write(f"content: {summary_content}\n")
            f.write(f"tags: session-summary\n")
            f.write(f"user_id: proj:dotclaude\n")
            f.write(f"sector: episodic\n")
    except Exception:
        pass

PYEOF

# Cleanup session start timestamp
SESSION_START_FILE="/tmp/session-start-${SESSION_ID}"
rm -f "$SESSION_START_FILE"

exit 0
