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
            chunks.append({
                "text": "\n".join(current_text),
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
        chunks.append({
            "text": "\n".join(current_text),
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
    session_tag = f"session-{today}"
    tags = json.dumps(["transcript", session_tag])

    # Test Ollama availability with first chunk
    first_vec = get_embedding(chunks[0]["text"])
    if first_vec is None:
        sys.exit(0)

    conn = sqlite3.connect(om_db, timeout=10)
    try:
        for idx, chunk in enumerate(chunks):
            simhash = hashlib.md5(chunk["text"].encode()).hexdigest()[:16]

            # Dedup by (session-tag, chunk_index)
            row = conn.execute(
                "SELECT 1 FROM memories WHERE tags LIKE ? AND meta LIKE ? AND user_id = ?",
                (f"%{session_tag}%", f'%"chunk_index": {idx}%', USER_ID)
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
