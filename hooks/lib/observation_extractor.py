#!/usr/bin/env python3
"""Extract observations from session transcripts and persist to tool-learnings.md + OpenMemory.

Usage: observation_extractor.py <sidecar_json> <om_db> <project_root> <session_id> <transcript_path>

Two detection layers:
  Layer 1 — Pattern matching on raw transcript (error recovery, repeated failure, approach pivot, discovery)
  Layer 2 — Embedding similarity against exemplar categories (reuses embeddings from sidecar)

Zero additional Ollama calls for Layer 2 (dot products against cached exemplar vectors).
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import sys
import time
import uuid
from urllib.request import urlopen, Request
from urllib.error import URLError


OLLAMA_URL = "http://localhost:11434/api/embeddings"
OLLAMA_MODEL = "nomic-embed-text"

SECTOR = "procedural"
USER_ID = "proj:dotclaude"
SALIENCE = 0.4
DECAY_LAMBDA = 0.07

SIMILARITY_THRESHOLD = 0.55
DEDUP_THRESHOLD = 0.80

EXEMPLAR_CATEGORIES = {
    "tool-workaround": [
        "tool returned error so used different approach to accomplish the same goal",
        "command failed due to shell escaping, switched to heredoc syntax instead",
        "MCP tool timed out, fell back to direct file read as workaround",
    ],
    "environment-discovery": [
        "system uses zsh not bash, changes glob expansion and quoting rules",
        "project uses monorepo with workspaces, imports resolve differently",
        "macOS stat flags differ from Linux, need platform detection",
    ],
    "pattern-recognition": [
        "codebase uses same error handling pattern across all modules consistently",
        "parsing logic duplicated in three files, could be extracted to shared utility",
        "all hooks follow the same stdin JSON parsing pattern for transcript data",
    ],
    "implicit-decision": [
        "chose direct SQL over MCP tool because hook runs outside Claude session context",
        "used simhash dedup over exact match to handle minor text variations",
        "picked background execution over foreground to avoid blocking session exit",
    ],
    "performance-insight": [
        "operation slow because sequential Ollama calls instead of batching embeddings",
        "query scanning all rows due to missing index on frequently filtered column",
        "file read in tight loop causes excessive IO, should batch or cache results",
    ],
}


# --- Embedding helpers (reused from signal_processor.py) ---

def _get_embedding(text):
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": text}).encode()
    req = Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("embedding")
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        return None


def _embedding_to_blob(vec):
    return struct.pack(f"<{len(vec)}f", *vec)


def _blob_to_embedding(blob):
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine_similarity(vec_a, vec_b):
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# --- Layer 1: Pattern matching on raw transcript ---

def extract_tool_events(entries):
    """Parse JSONL entries into structured tool events.

    Pairs tool_use (in assistant messages) with tool_result (in user messages)
    via tool_use_id. Returns list of dicts with tool info.
    """
    events = []
    pending_calls = {}  # tool_use_id -> event dict

    for entry_idx, entry in enumerate(entries):
        role = entry.get("type", "")
        msg = entry.get("message", "")

        if role == "assistant" and isinstance(msg, dict):
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        event = {
                            "entry_idx": entry_idx,
                            "tool_use_id": tool_id,
                            "tool_name": block.get("name", ""),
                            "input": block.get("input", {}),
                            "result": None,
                            "is_error": False,
                            "error_content": "",
                        }
                        pending_calls[tool_id] = event
                        events.append(event)

        elif role == "user":
            # tool_result entries come as user messages
            if isinstance(msg, list):
                results = msg
            elif isinstance(msg, dict):
                c = msg.get("content", [])
                results = c if isinstance(c, list) else []
            else:
                continue

            for block in results:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    tool_id = block.get("tool_use_id", "")
                    content = block.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        )

                    is_error = block.get("is_error", False)
                    # Also check content for error signals even when is_error=False
                    error_signals = re.compile(
                        r'Exit code|command not found|No such file|Permission denied|'
                        r'Traceback|Error:|FAILED|fatal:|error\[',
                        re.IGNORECASE
                    )
                    has_error_content = bool(error_signals.search(str(content)[:2000]))

                    if tool_id in pending_calls:
                        pending_calls[tool_id]["result"] = str(content)[:2000]
                        pending_calls[tool_id]["is_error"] = is_error or has_error_content
                        if is_error or has_error_content:
                            pending_calls[tool_id]["error_content"] = str(content)[:500]

    return events


def _file_from_event(event):
    """Extract file path from a tool event's input."""
    inp = event.get("input", {})
    return inp.get("file_path", "") or inp.get("command", "")[:200]


def _word_overlap(text_a, text_b):
    words_a = set(re.findall(r'\w{3,}', text_a.lower()))
    words_b = set(re.findall(r'\w{3,}', text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / min(len(words_a), len(words_b))


def detect_error_recovery(events):
    """Layer 1 pattern 1: Tool error within N=5 events of a success addressing the same goal."""
    observations = []
    error_events = [e for e in events if e["is_error"]]

    for err in error_events:
        err_idx = events.index(err)
        err_file = _file_from_event(err)

        # Look forward up to 5 events for a recovery
        for j in range(err_idx + 1, min(err_idx + 6, len(events))):
            candidate = events[j]
            if candidate["is_error"]:
                continue

            cand_file = _file_from_event(candidate)
            # Same file path or >30% word overlap
            same_file = err_file and cand_file and (
                os.path.basename(err_file) == os.path.basename(cand_file)
                if "/" in err_file and "/" in cand_file
                else _word_overlap(err_file, cand_file) > 0.3
            )
            word_match = _word_overlap(
                err.get("error_content", "") + " " + _file_from_event(err),
                (candidate.get("result", "") or "") + " " + _file_from_event(candidate),
            ) > 0.3

            if same_file or word_match:
                error_msg = err.get("error_content", "")[:200]
                recovery = f"{candidate['tool_name']} on {os.path.basename(cand_file)}" if cand_file else candidate["tool_name"]
                obs = f"{err['tool_name']} failed: {error_msg}. Recovery: {recovery}"
                observations.append({
                    "text": obs[:500],
                    "source": "error-recovery",
                })
                break

    return observations


def detect_repeated_failure(events):
    """Layer 1 pattern 2: Same tool type fails 3+ times before succeeding."""
    observations = []
    # Group consecutive failures by tool name
    i = 0
    while i < len(events):
        if not events[i]["is_error"]:
            i += 1
            continue

        tool_name = events[i]["tool_name"]
        fail_count = 0
        first_error = events[i].get("error_content", "")
        j = i

        while j < len(events) and events[j]["tool_name"] == tool_name and events[j]["is_error"]:
            fail_count += 1
            j += 1

        # Check if next event of same type succeeded
        success = j < len(events) and events[j]["tool_name"] == tool_name and not events[j]["is_error"]

        if fail_count >= 3 and success:
            last_error = events[j - 1].get("error_content", "")[:150]
            fix_info = _file_from_event(events[j])[:100]
            obs = f"{tool_name} failed {fail_count}x. First error: {first_error[:150]}. Final fix: {fix_info}"
            observations.append({
                "text": obs[:500],
                "source": "repeated-failure",
            })

        i = j if j > i else i + 1

    return observations


def extract_assistant_turns(entries):
    """Extract assistant text turns for pattern matching."""
    turns = []
    for idx, entry in enumerate(entries):
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", "")
        text = ""
        if isinstance(msg, str):
            text = msg
        elif isinstance(msg, dict):
            c = msg.get("content", "")
            if isinstance(c, str):
                text = c
            elif isinstance(c, list):
                text = " ".join(
                    p.get("text", "") for p in c
                    if isinstance(p, dict) and p.get("type") == "text"
                )
        if text.strip():
            turns.append({"idx": idx, "text": text.strip()})
    return turns


PLAN_LANGUAGE = re.compile(r"\b(I'll|let me|I'm going to|going to try|plan is to)\b", re.IGNORECASE)
PIVOT_LANGUAGE = re.compile(r"\b(instead|actually|different approach|on second thought|better to|switching to)\b", re.IGNORECASE)


def detect_approach_pivot(turns):
    """Layer 1 pattern 3: Plan language followed by pivot language within 5 turns."""
    observations = []

    for i, turn in enumerate(turns):
        if not PLAN_LANGUAGE.search(turn["text"]):
            continue

        plan_snippet = turn["text"][:200]

        for j in range(i + 1, min(i + 6, len(turns))):
            pivot_match = PIVOT_LANGUAGE.search(turns[j]["text"])
            if pivot_match:
                pivot_snippet = turns[j]["text"][:200]
                obs = f"Approach pivot: planned '{plan_snippet[:100]}...' then switched: '{pivot_snippet[:100]}...'"
                observations.append({
                    "text": obs[:500],
                    "source": "approach-pivot",
                })
                break

    return observations


DISCOVERY_MARKERS = re.compile(
    r"\b(turns out|didn't expect|I was wrong about|contrary to|surprisingly|"
    r"TIL|learned that|discovered that|realized that)\b",
    re.IGNORECASE,
)


def detect_discovery_language(turns):
    """Layer 1 pattern 4: Discovery markers with >50 chars of substance."""
    observations = []

    for turn in turns:
        match = DISCOVERY_MARKERS.search(turn["text"])
        if not match:
            continue

        # Extract substance after the marker
        after_marker = turn["text"][match.end():].strip()
        if len(after_marker) < 50:
            continue

        # Filter hedging — skip if it's mostly questions or conditionals
        hedging = re.compile(r"^(maybe|perhaps|might|could be|not sure|I think)", re.IGNORECASE)
        if hedging.match(after_marker):
            continue

        obs = f"Discovery: {turn['text'][match.start():match.start()+300]}"
        observations.append({
            "text": obs[:500],
            "source": "discovery",
        })

    return observations


# --- Layer 2: Embedding similarity ---

def load_exemplar_embeddings(cache_path):
    """Load or generate exemplar embeddings cache.

    Returns dict: category -> list of embedding vectors.
    Returns None if Ollama is unavailable.
    """
    if os.path.isfile(cache_path):
        try:
            with open(cache_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Generate cache
    cache = {}
    for category, texts in EXEMPLAR_CATEGORIES.items():
        vecs = []
        for text in texts:
            vec = _get_embedding(text)
            if vec is None:
                return None  # Ollama unavailable
            vecs.append(vec)
        cache[category] = vecs

    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache, f)
    except OSError:
        pass

    return cache


def classify_chunk(chunk_vec, exemplars, threshold):
    """Compare chunk embedding against all exemplar vectors.

    Returns (category, max_similarity) or (None, 0) if below threshold.
    """
    best_cat = None
    best_sim = threshold

    for category, vecs in exemplars.items():
        for vec in vecs:
            sim = _cosine_similarity(chunk_vec, vec)
            if sim > best_sim:
                best_sim = sim
                best_cat = category

    return best_cat, best_sim


# --- Dedup ---

def is_duplicate(obs_text, conn):
    """Check simhash + semantic dedup against existing observations in OpenMemory."""
    simhash = hashlib.md5(obs_text.lower().strip().encode()).hexdigest()[:16]

    row = conn.execute("SELECT 1 FROM memories WHERE simhash = ?", (simhash,)).fetchone()
    if row:
        return True

    # Semantic dedup: check against existing observation entries
    rows = conn.execute(
        "SELECT mean_vec FROM memories WHERE tags LIKE '%observation%' AND mean_vec IS NOT NULL"
    ).fetchall()

    if not rows:
        return False

    obs_vec = _get_embedding(obs_text)
    if obs_vec is None:
        return False  # Can't check semantic dedup, allow through

    for (blob,) in rows:
        existing_vec = _blob_to_embedding(blob)
        if _cosine_similarity(obs_vec, existing_vec) > DEDUP_THRESHOLD:
            return True

    return False


# --- Persistence ---

def persist_observation(obs, conn, project_root, session_id):
    """Dual-write: tool-learnings.md (audit trail) + OpenMemory (queryable)."""
    text = obs["text"]
    source = obs["source"]
    today = time.strftime("%Y-%m-%d")

    # 1. Append to tool-learnings.md
    learnings_path = os.path.join(project_root, "tool-learnings.md")
    entry = f"- [{today}] AUTO: {text} (source: {source}, session: {session_id[:8] if session_id else 'unknown'})\n"

    try:
        with open(learnings_path, "a") as f:
            f.write(entry)
    except OSError:
        pass

    # 2. Insert into OpenMemory
    simhash = hashlib.md5(text.lower().strip().encode()).hexdigest()[:16]
    vec = obs.get("embedding") or _get_embedding(text)
    if vec is None:
        return

    blob = _embedding_to_blob(vec)
    mem_id = str(uuid.uuid4())
    now_ts = int(time.time())
    tags = json.dumps(["observation", source, "auto-extracted"], separators=(",", ":"))
    meta = json.dumps({"session_id": session_id, "source": source})

    conn.execute(
        "INSERT OR IGNORE INTO memories "
        "(id, user_id, content, simhash, primary_sector, tags, meta, "
        "mean_dim, mean_vec, created_at, updated_at, last_seen_at, "
        "salience, decay_lambda, feedback_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            mem_id, USER_ID, text[:4000], simhash,
            SECTOR, tags, meta,
            len(vec), blob,
            now_ts, now_ts, now_ts,
            SALIENCE, DECAY_LAMBDA, 0,
        ),
    )


# --- Main ---

def main():
    if len(sys.argv) < 5:
        print("Usage: observation_extractor.py <sidecar_json> <om_db> <project_root> <session_id> [transcript_path]",
              file=sys.stderr)
        sys.exit(1)

    sidecar_path = sys.argv[1]
    om_db = sys.argv[2]
    project_root = sys.argv[3]
    session_id = sys.argv[4] if len(sys.argv) > 4 else ""
    transcript_path = sys.argv[5] if len(sys.argv) > 5 else ""

    if not os.path.isfile(sidecar_path) or not os.path.isfile(om_db):
        sys.exit(0)

    # Load sidecar (chunks with pre-computed embeddings from transcript_embedder)
    try:
        with open(sidecar_path) as f:
            chunks = json.load(f)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    if not chunks:
        sys.exit(0)

    # --- Layer 1: Pattern matching on raw transcript ---
    layer1_observations = []

    if transcript_path and os.path.isfile(transcript_path):
        entries = []
        try:
            with open(transcript_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            entries = []

        if entries:
            if len(entries) > 5000:
                entries = entries[-2000:]

            tool_events = extract_tool_events(entries)
            layer1_observations.extend(detect_error_recovery(tool_events))
            layer1_observations.extend(detect_repeated_failure(tool_events))

            assistant_turns = extract_assistant_turns(entries)
            layer1_observations.extend(detect_approach_pivot(assistant_turns))
            layer1_observations.extend(detect_discovery_language(assistant_turns))

    # --- Layer 2: Embedding similarity ---
    layer2_observations = []

    # Chunks matched by Layer 1 (by turn range overlap) are excluded from Layer 2
    l1_texts = {obs["text"] for obs in layer1_observations}

    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exemplar_cache.json")
    exemplars = load_exemplar_embeddings(cache_path)

    if exemplars:
        for chunk in chunks:
            embedding = chunk.get("embedding")
            if not embedding:
                continue

            text = chunk.get("text", "")
            if not text or len(text) < 100:
                continue

            # Skip if chunk text substantially overlaps with a Layer 1 observation
            if any(_word_overlap(text, l1_text) > 0.5 for l1_text in l1_texts):
                continue

            category, similarity = classify_chunk(embedding, exemplars, SIMILARITY_THRESHOLD)
            if category:
                # Extract the most informative sentence from the chunk
                sentences = re.split(r'[.!?\n]', text)
                best_sentence = max(sentences, key=len).strip() if sentences else text[:200]
                obs_text = f"{best_sentence[:300]}"

                layer2_observations.append({
                    "text": obs_text,
                    "source": category,
                    "embedding": embedding,
                })

    # --- Dedup and persist ---
    all_observations = layer1_observations + layer2_observations

    if not all_observations:
        sys.exit(0)

    conn = sqlite3.connect(om_db, timeout=10)
    persisted = 0

    try:
        for obs in all_observations:
            if is_duplicate(obs["text"], conn):
                continue
            persist_observation(obs, conn, project_root, session_id)
            persisted += 1

        conn.commit()
    finally:
        conn.close()

    if persisted > 0:
        print(f"Observations: {persisted} new entries persisted ({len(layer1_observations)} L1, {len(layer2_observations)} L2)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
