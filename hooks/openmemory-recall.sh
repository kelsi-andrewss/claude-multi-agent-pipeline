#!/bin/bash
# UserPromptSubmit hook — injects relevant OpenMemory memories into context.
# Reads user prompt from stdin JSON, queries openmemory.sqlite using keyword matching,
# prints a MEMORY RECALL block to stdout if matches are found.
# Exits silently (no output) if no matches or DB is missing.

DB="$HOME/.claude/.claude/openmemory.sqlite"

if [[ ! -f "$DB" ]]; then
  exit 0
fi

INPUT=$(cat)

python3 - <<'PYEOF' "$DB" "$INPUT"
import sys
import json
import sqlite3
import re

DB_PATH = sys.argv[1]
raw_input = sys.argv[2]

STOP_WORDS = {
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
    'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his',
    'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'who', 'any',
    'did', 'she', 'use', 'way', 'about', 'after', 'also', 'back', 'been',
    'come', 'could', 'each', 'from', 'give', 'have', 'here', 'just', 'know',
    'like', 'look', 'make', 'more', 'most', 'move', 'much', 'need', 'only',
    'open', 'over', 'same', 'some', 'take', 'than', 'that', 'them', 'then',
    'there', 'they', 'this', 'time', 'very', 'well', 'were', 'what', 'when',
    'will', 'with', 'would', 'your', 'into', 'been', 'does', 'even', 'from',
    'such', 'through', 'which', 'while', 'should', 'these', 'those', 'being',
    'where', 'their', 'before', 'between',
}

try:
    d = json.loads(raw_input)
    prompt = d.get('input', '')
    if isinstance(prompt, dict):
        content = prompt.get('content', '')
        if isinstance(content, list):
            prompt = ' '.join(
                p.get('text', '') for p in content
                if isinstance(p, dict) and p.get('type') == 'text'
            )
        elif isinstance(content, str):
            prompt = content
except Exception:
    sys.exit(0)

if not prompt or not isinstance(prompt, str):
    sys.exit(0)

words = re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', prompt.lower())
keywords = [w for w in words if len(w) > 3 and w not in STOP_WORDS]

if not keywords:
    sys.exit(0)

keywords = list(dict.fromkeys(keywords))[:10]

try:
    conn = sqlite3.connect(DB_PATH, timeout=1.0)
    cursor = conn.cursor()

    like_clauses = ' OR '.join(['content LIKE ?'] * len(keywords))
    params = ['%' + kw + '%' for kw in keywords]

    match_count_expr = ' + '.join(
        ['(CASE WHEN content LIKE ? THEN 1 ELSE 0 END)'] * len(keywords)
    )

    query = f"""
        SELECT id, content, tags, feedback_score, created_at,
               ({match_count_expr}) AS match_count
        FROM memories
        WHERE {like_clauses}
        ORDER BY match_count DESC, feedback_score DESC, created_at DESC
        LIMIT 3
    """

    cursor.execute(query, params + params)
    rows = cursor.fetchall()
    conn.close()
except Exception:
    sys.exit(0)

if not rows:
    sys.exit(0)

lines = ['=== MEMORY RECALL ===']
for row in rows:
    mem_id, content, tags_raw, feedback_score, created_at, match_count = row
    try:
        tags = json.loads(tags_raw) if tags_raw else []
        tag_str = '[' + ', '.join(tags) + ']' if tags else ''
    except Exception:
        tag_str = ''
    preview = (content or '').strip().replace('\n', ' ')
    if len(preview) > 200:
        preview = preview[:197] + '...'
    if tag_str:
        lines.append(f'- {tag_str} {preview}')
    else:
        lines.append(f'- {preview}')
lines.append('=== END MEMORY RECALL ===')

print('\n'.join(lines))
PYEOF
