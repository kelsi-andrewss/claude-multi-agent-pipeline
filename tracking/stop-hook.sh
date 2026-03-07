#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --backfill-only: run backfill for current project and exit (used by SessionStart hook)
if [[ "${1:-}" == "--backfill-only" ]]; then
  INPUT="$(cat)"
  CWD="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || true)"
  if [[ -z "$CWD" ]]; then exit 0; fi
  PROJECT_ROOT="$CWD"
  while [[ "$PROJECT_ROOT" != "/" ]]; do
    [[ -d "$PROJECT_ROOT/.git" ]] && break
    PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
  done
  if [[ "$PROJECT_ROOT" == "/" ]]; then exit 0; fi
  TRACKING_DIR="$PROJECT_ROOT/.claude/tracking"
  if [[ -d "$TRACKING_DIR" ]]; then
    python3 "$SCRIPT_DIR/backfill.py" "$PROJECT_ROOT" 2>/dev/null || true
  fi
  exit 0
fi

INPUT="$(cat)"

# Prevent loops
STOP_ACTIVE="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stop_hook_active', False))" 2>/dev/null || echo "False")"
if [[ "$STOP_ACTIVE" == "True" ]]; then exit 0; fi

# Extract fields
CWD="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || true)"
TRANSCRIPT="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || true)"
SESSION_ID="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || true)"

if [[ -z "$CWD" || -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]]; then exit 0; fi

# Find project root (walk up to .git)
PROJECT_ROOT="$CWD"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -d "$PROJECT_ROOT/.git" ]] && break
  PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
done
if [[ "$PROJECT_ROOT" == "/" ]]; then exit 0; fi

TRACKING_DIR="$PROJECT_ROOT/.claude/tracking"

# Auto-initialize if missing, then backfill
if [[ ! -d "$TRACKING_DIR" ]]; then
  bash "$SCRIPT_DIR/init-templates.sh" "$TRACKING_DIR"
  python3 "$SCRIPT_DIR/backfill.py" "$PROJECT_ROOT" 2>/dev/null || true
fi

# Parse token usage from JSONL — emit one entry per turn, upsert into tokens.json
python3 - "$TRANSCRIPT" "$TRACKING_DIR/tokens.json" "$SESSION_ID" "$(basename "$PROJECT_ROOT")" <<'PYEOF'
import sys, json, os
from datetime import datetime, date

transcript_path = sys.argv[1]
tokens_file = sys.argv[2]
session_id = sys.argv[3]
project_name = sys.argv[4]

msgs = []       # (role, timestamp)
usages = []     # usage dicts from assistant messages, in order
model = "unknown"

with open(transcript_path) as f:
    for line in f:
        try:
            obj = json.loads(line)
            t = obj.get('type')
            ts = obj.get('timestamp')
            if t == 'user' and not obj.get('isSidechain') and ts:
                msgs.append(('user', ts))
            elif t == 'assistant' and ts:
                msgs.append(('assistant', ts))
            msg = obj.get('message', {})
            if isinstance(msg, dict) and msg.get('role') == 'assistant':
                usage = msg.get('usage', {})
                if usage:
                    usages.append(usage)
                m = msg.get('model', '')
                if m:
                    model = m
        except:
            pass

# Build per-turn entries
turn_entries = []
turn_index = 0
usage_index = 0
i = 0
while i < len(msgs):
    if msgs[i][0] == 'user':
        user_ts = msgs[i][1]
        j = i + 1
        while j < len(msgs) and msgs[j][0] != 'assistant':
            j += 1
        if j < len(msgs):
            asst_ts = msgs[j][1]
            usage = {}
            if usage_index < len(usages):
                usage = usages[usage_index]
                usage_index += 1

            inp = usage.get('input_tokens', 0)
            out = usage.get('output_tokens', 0)
            cache_create = usage.get('cache_creation_input_tokens', 0)
            cache_read = usage.get('cache_read_input_tokens', 0)
            total = inp + cache_create + cache_read + out

            if total > 0:
                duration = 0
                try:
                    t0 = datetime.fromisoformat(user_ts.replace('Z', '+00:00'))
                    t1 = datetime.fromisoformat(asst_ts.replace('Z', '+00:00'))
                    duration = max(0, int((t1 - t0).total_seconds()))
                except:
                    pass

                if 'opus' in model:
                    cost = inp * 15 / 1e6 + cache_create * 18.75 / 1e6 + cache_read * 1.50 / 1e6 + out * 75 / 1e6
                else:
                    cost = inp * 3 / 1e6 + cache_create * 3.75 / 1e6 + cache_read * 0.30 / 1e6 + out * 15 / 1e6

                try:
                    turn_ts = datetime.fromisoformat(user_ts.replace('Z', '+00:00')).strftime('%Y-%m-%dT%H:%M:%SZ')
                    turn_date = datetime.fromisoformat(user_ts.replace('Z', '+00:00')).strftime('%Y-%m-%d')
                except:
                    turn_ts = user_ts
                    turn_date = date.today().isoformat()

                turn_entries.append({
                    'date': turn_date,
                    'project': project_name,
                    'session_id': session_id,
                    'turn_index': turn_index,
                    'turn_timestamp': turn_ts,
                    'input_tokens': inp,
                    'cache_creation_tokens': cache_create,
                    'cache_read_tokens': cache_read,
                    'output_tokens': out,
                    'total_tokens': total,
                    'estimated_cost_usd': round(cost, 4),
                    'model': model,
                    'duration_seconds': duration,
                })
            turn_index += 1
            i = j + 1
        else:
            i += 1
    else:
        i += 1

if not turn_entries:
    sys.exit(0)

# Load existing data
data = []
if os.path.exists(tokens_file):
    try:
        with open(tokens_file) as f:
            data = json.load(f)
    except:
        data = []

# Build index of existing (session_id, turn_index) -> position
existing_idx = {}
for pos, e in enumerate(data):
    key = (e.get('session_id'), e.get('turn_index'))
    existing_idx[key] = pos

# Check if anything actually changed
changed = False
for entry in turn_entries:
    key = (entry['session_id'], entry['turn_index'])
    if key not in existing_idx:
        changed = True
        break
    existing = data[existing_idx[key]]
    if (existing.get('total_tokens') != entry['total_tokens'] or
        existing.get('output_tokens') != entry['output_tokens']):
        changed = True
        break

if not changed:
    sys.exit(0)

# Upsert: update existing entries or append new ones
for entry in turn_entries:
    key = (entry['session_id'], entry['turn_index'])
    if key in existing_idx:
        data[existing_idx[key]] = entry
    else:
        data.append(entry)
        existing_idx[key] = len(data) - 1

# Sort by (date, session_id, turn_index)
data.sort(key=lambda x: (x.get('date', ''), x.get('session_id', ''), x.get('turn_index', 0)))

with open(tokens_file, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
PYEOF

# Parse transcript for errors — tool errors, agent failures, hook rejections
python3 - "$TRANSCRIPT" "$TRACKING_DIR/errors.json" "$SESSION_ID" <<'ERREOF'
import sys, json, os
from datetime import datetime

transcript_path = sys.argv[1]
errors_file = sys.argv[2]
session_id = sys.argv[3]
today = datetime.now().strftime('%Y-%m-%d')

errors = []

with open(transcript_path, encoding='utf-8') as f:
    for line in f:
        try:
            obj = json.loads(line)
        except:
            continue

        # Check for tool_result errors in user messages
        msg = obj.get('message', {})
        if obj.get('type') != 'user':
            continue
        content = msg.get('content', []) if isinstance(msg, dict) else msg if isinstance(msg, list) else []
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get('type') != 'tool_result':
                continue

            is_error = block.get('is_error', False)
            result_content = block.get('content', '')
            if isinstance(result_content, list):
                result_content = ' '.join(
                    p.get('text', '') for p in result_content
                    if isinstance(p, dict) and p.get('type') == 'text'
                )

            error_type = None
            if is_error:
                error_type = 'tool_error'
            elif 'hook' in str(result_content).lower() and ('BLOCKED' in str(result_content) or 'blocked' in str(result_content)):
                error_type = 'hook_rejection'
            elif any(kw in str(result_content) for kw in ['BLOCKED', 'FAILED', 'Exit code']):
                error_type = 'agent_failure'

            if error_type:
                # Find the tool name from the matching tool_use_id
                tool_name = block.get('tool_use_id', 'unknown')[:20]
                errors.append({
                    'date': today,
                    'session_id': session_id,
                    'tool': tool_name,
                    'error_type': error_type,
                    'message': str(result_content)[:200],
                })

if not errors:
    sys.exit(0)

# Load and append
existing = []
if os.path.exists(errors_file):
    try:
        with open(errors_file) as f:
            existing = json.load(f)
    except:
        existing = []

# Dedup by (session_id, message[:50])
seen = {(e['session_id'], e['message'][:50]) for e in existing}
for err in errors:
    key = (err['session_id'], err['message'][:50])
    if key not in seen:
        existing.append(err)
        seen.add(key)

with open(errors_file, 'w') as f:
    json.dump(existing, f, indent=2)
    f.write('\n')
ERREOF

# Parse transcript for skill invocations and outcomes
python3 - "$TRANSCRIPT" "$TRACKING_DIR/skill-metrics.json" "$SESSION_ID" <<'SKILLEOF'
import sys, json, os
from datetime import datetime

transcript_path = sys.argv[1]
metrics_file = sys.argv[2]
session_id = sys.argv[3]
today = datetime.now().strftime('%Y-%m-%d')

# Find Skill tool_use calls and their outcomes
entries = []
with open(transcript_path, encoding='utf-8') as f:
    for line in f:
        try:
            entries.append(json.loads(line))
        except:
            continue

skills = []
for i, entry in enumerate(entries):
    if entry.get('type') != 'assistant':
        continue
    msg = entry.get('message', {})
    if not isinstance(msg, dict):
        continue
    content = msg.get('content', [])
    if not isinstance(content, list):
        continue

    for block in content:
        if not isinstance(block, dict) or block.get('type') != 'tool_use':
            continue
        if block.get('name') != 'Skill':
            continue

        skill_name = block.get('input', {}).get('skill', 'unknown')
        ts = entry.get('timestamp', '')

        # Look forward for Agent results to determine outcome
        outcome = 'unknown'
        stories_created = 0
        stories_completed = 0
        end_ts = ''

        for j in range(i + 1, min(i + 100, len(entries))):
            later = entries[j]
            if later.get('type') == 'assistant':
                later_msg = later.get('message', {})
                if isinstance(later_msg, dict):
                    later_content = later_msg.get('content', [])
                    if isinstance(later_content, list):
                        text = ' '.join(
                            p.get('text', '') for p in later_content
                            if isinstance(p, dict) and p.get('type') == 'text'
                        )
                        if 'BLOCKED' in text or 'FAILED' in text:
                            outcome = 'failure'
                            end_ts = later.get('timestamp', '')
                            break
                        if 'Ship complete' in text or 'merged' in text.lower():
                            outcome = 'success'
                            end_ts = later.get('timestamp', '')
                            # Count stories
                            import re
                            stories_created = len(re.findall(r'story-\d+', text))
                            stories_completed = text.lower().count('merged') + text.lower().count('done')
                            break

        # Calculate duration
        duration = 0
        if ts and end_ts:
            try:
                t0 = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                t1 = datetime.fromisoformat(end_ts.replace('Z', '+00:00'))
                duration = max(0, int((t1 - t0).total_seconds()))
            except:
                pass

        skills.append({
            'date': today,
            'session_id': session_id,
            'skill': skill_name,
            'duration_seconds': duration,
            'outcome': outcome,
            'stories_created': stories_created,
            'stories_completed': stories_completed,
        })

if not skills:
    sys.exit(0)

existing = []
if os.path.exists(metrics_file):
    try:
        with open(metrics_file) as f:
            existing = json.load(f)
    except:
        existing = []

# Dedup by (session_id, skill)
seen = {(e['session_id'], e['skill']) for e in existing}
for s in skills:
    key = (s['session_id'], s['skill'])
    if key not in seen:
        existing.append(s)
        seen.add(key)

with open(metrics_file, 'w') as f:
    json.dump(existing, f, indent=2)
    f.write('\n')
SKILLEOF

# Regenerate charts
python3 "$SCRIPT_DIR/generate-charts.py" "$TRACKING_DIR/tokens.json" "$TRACKING_DIR/charts.html" 2>/dev/null || true

# Regenerate key-prompts index
python3 "$SCRIPT_DIR/update-prompts-index.py" "$TRACKING_DIR" 2>/dev/null || true
