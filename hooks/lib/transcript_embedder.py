#!/usr/bin/env python3
"""Chunk a Claude Code transcript and embed into OpenMemory.

Usage: python3 transcript_embedder.py <transcript_path> <om_db_path>

Parses JSONL transcript, groups turns into ~500-token chunks,
calls Ollama nomic-embed-text for embeddings, and inserts into
openmemory.sqlite with simhash dedup.
"""

import hashlib
import json
import os
import re
import sqlite3
import struct
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "nomic-embed-text"
CHUNK_TOKEN_TARGET = 500
MIN_CONTENT_LENGTH = 200

SYSTEM_MSG = re.compile(
    r'<(local-command-caveat|task-notification|system-reminder|command-name|command-message)>|'
    r'^Base directory for this skill|'
    r'^Implement the following plan:|'
    r'^<skill-|'
    r'^(Merging|Already merged|Cleaning up|All .* merged)|'
    r'^User has requested:|'
    r'^ToolSearch:|'
    r'^select:mcp__|'
    r'^## Coder Result|'
    r'^(Merged|Worktree removed|Branch deleted|Story updated|Epic updated|Branch cleanup):|'
    r'^(Commit|commit) [0-9a-f]{7,40}|'
    r'^\s*```\s*$|'
    r'^(Ship complete|Run complete|Hotfix|Integration verified):|'
    r'^Full transcript available at:|'
    r'^\s*\|.*\|.*\||'
    r'^story-\d+\s+(batch|DONE|BLOCKED)',
    re.IGNORECASE | re.MULTILINE
)
SECTOR = "episodic"
USER_ID = "proj:dotclaude"
SALIENCE = 0.3
DECAY_LAMBDA = 0.07


def parse_transcript(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def extract_turns(entries):
    turns = []
    for entry in entries:
        role = entry.get("type", "")
        if role not in ("user", "assistant"):
            continue

        msg = entry.get("message", "")
        ts = entry.get("timestamp", "")
        content = ""

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
        elif isinstance(msg, list):
            content = " ".join(
                p.get("text", "") for p in msg
                if isinstance(p, dict) and p.get("type") == "text"
            )

        content = content.strip()
        if content:
            turns.append({"role": role, "content": content, "ts": ts})

    return turns


def estimate_tokens(text):
    return len(text) // 4


def filter_system_lines(text):
    return "\n".join(
        line for line in text.split("\n")
        if not SYSTEM_MSG.match(line.strip())
    )


def is_repetitive(text):
    lines = [l for l in text.split('\n') if l.strip()]
    if len(lines) < 4:
        return False
    short_exchanges = sum(
        1 for l in lines
        if (l.startswith('User: ') or l.startswith('Assistant: '))
        and len(l.split(': ', 1)[-1]) <= 30
    )
    return short_exchanges / len(lines) > 0.5


def chunk_turns(turns):
    chunks = []
    current_text = []
    current_tokens = 0
    chunk_start = 0

    for i, turn in enumerate(turns):
        prefix = "User: " if turn["role"] == "user" else "Assistant: "
        segment = prefix + turn["content"]
        seg_tokens = estimate_tokens(segment)

        if current_tokens + seg_tokens > CHUNK_TOKEN_TARGET and current_text:
            raw = "\n".join(current_text)
            filtered = filter_system_lines(raw)
            if len(filtered) >= MIN_CONTENT_LENGTH and not is_repetitive(filtered):
                chunks.append({
                    "text": filtered,
                    "turn_start": chunk_start,
                    "turn_end": i - 1,
                })
            current_text = []
            current_tokens = 0
            chunk_start = i

        # Truncate individual segments that exceed 2x target
        if seg_tokens > CHUNK_TOKEN_TARGET * 2:
            segment = segment[:CHUNK_TOKEN_TARGET * 8]
            seg_tokens = CHUNK_TOKEN_TARGET

        current_text.append(segment)
        current_tokens += seg_tokens

    if current_text:
        raw = "\n".join(current_text)
        filtered = filter_system_lines(raw)
        if len(filtered) >= MIN_CONTENT_LENGTH and not is_repetitive(filtered):
            chunks.append({
                "text": filtered,
                "turn_start": chunk_start,
                "turn_end": len(turns) - 1,
            })

    return chunks


def get_embedding(text):
    payload = json.dumps({"model": MODEL, "prompt": text}).encode()
    req = Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("embedding")
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        return None


def embedding_to_blob(vec):
    return struct.pack(f"<{len(vec)}f", *vec)


def normalize_tags(conn):
    conn.execute("UPDATE memories SET tags = REPLACE(tags, ', ', ',') WHERE tags LIKE '%, %'")
    conn.commit()


def main():
    if len(sys.argv) < 3:
        sys.exit(1)

    transcript_path = sys.argv[1]
    om_db = sys.argv[2]

    if not os.path.isfile(transcript_path) or not os.path.isfile(om_db):
        sys.exit(0)

    entries = parse_transcript(transcript_path)
    if not entries:
        sys.exit(0)

    turns = extract_turns(entries)
    if not turns:
        sys.exit(0)

    chunks = chunk_turns(turns)
    if not chunks:
        sys.exit(0)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_ts = int(time.time())
    tags = json.dumps(["transcript", f"session-{today}"], separators=(',', ':'))

    # Test Ollama availability with first chunk
    first_vec = get_embedding(chunks[0]["text"])
    if first_vec is None:
        sys.exit(0)

    conn = sqlite3.connect(om_db, timeout=10)
    normalize_tags(conn)
    try:
        for idx, chunk in enumerate(chunks):
            simhash = hashlib.md5(chunk["text"].encode()).hexdigest()[:16]

            row = conn.execute(
                "SELECT 1 FROM memories WHERE simhash = ?", (simhash,)
            ).fetchone()
            if row:
                continue

            if idx == 0:
                vec = first_vec
            else:
                vec = get_embedding(chunk["text"])
                if vec is None:
                    continue

            blob = embedding_to_blob(vec)
            mem_id = str(uuid.uuid4())
            meta = json.dumps({
                "chunk_index": idx,
                "turn_range": [chunk["turn_start"], chunk["turn_end"]],
            })

            conn.execute(
                "INSERT OR IGNORE INTO memories "
                "(id, user_id, content, simhash, primary_sector, tags, meta, "
                "mean_dim, mean_vec, created_at, updated_at, last_seen_at, "
                "salience, decay_lambda, feedback_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mem_id, USER_ID, chunk["text"][:4000], simhash,
                    SECTOR, tags, meta,
                    len(vec), blob,
                    now_ts, now_ts, now_ts,
                    SALIENCE, DECAY_LAMBDA, 0,
                ),
            )

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
