#!/usr/bin/env python3
"""Centralized OpenMemory write gate.

All OM writes should go through om_write() to enforce tag whitelist,
dedup, budget limits, and ops logging.
"""
import hashlib, json, math, os, sqlite3, struct, sys, time, uuid
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

ALLOWED_TAGS = {
    "behavioral-pref",
    "tool-learning",
    "decision",
    "prompt-pattern",
    "session-summary",
    "critique-learning",
    "gemini-blind-spot",
}

BUDGETS = {
    "behavioral-pref": 30,
    "tool-learning": 30,
    "decision": 50,
    "prompt-pattern": 30,
    "session-summary": 20,
    "critique-learning": 30,
    "gemini-blind-spot": 20,
}

OM_DB_PATH = os.path.expanduser("~/.claude/.claude/openmemory.sqlite")
OLLAMA_URL = "http://localhost:11434/api/embeddings"
OLLAMA_MODEL = "nomic-embed-text"
OPS_LOG_PATH = os.path.expanduser("~/.claude/.claude/tracking/om-ops.json")
DEDUP_THRESHOLD = 0.85
PRUNE_THRESHOLD = 0.01
DEFAULT_DECAY = 0.05


def _log_op(op_type, details=None):
    try:
        entry = {
            "date": datetime.now(timezone.utc).isoformat(),
            "op": op_type,
            "details": details or {},
        }
        os.makedirs(os.path.dirname(OPS_LOG_PATH), exist_ok=True)
        with open(OPS_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _get_embedding(text):
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": text}).encode()
    req = Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("embedding")
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        return None


def _cosine_similarity(vec_a, vec_b):
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embedding_to_blob(vec):
    return struct.pack(f"<{len(vec)}f", *vec)


def _blob_to_embedding(blob):
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _compute_simhash(content):
    return hashlib.md5(content.lower().strip().encode()).hexdigest()[:16]


def dedup_check(content, primary_tag):
    embedding = _get_embedding(content)

    if embedding is not None:
        try:
            conn = sqlite3.connect(OM_DB_PATH, timeout=10)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, mean_vec FROM memories WHERE tags LIKE ? AND mean_vec IS NOT NULL",
                (f"%{primary_tag}%",),
            )
            rows = cursor.fetchall()
            conn.close()

            for row_id, blob in rows:
                stored_vec = _blob_to_embedding(blob)
                sim = _cosine_similarity(embedding, stored_vec)
                if sim >= DEDUP_THRESHOLD:
                    return row_id
        except sqlite3.Error:
            pass
        return None

    _log_op("ollama_fallback", {"reason": "embedding unavailable for dedup"})
    simhash = _compute_simhash(content)
    try:
        conn = sqlite3.connect(OM_DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM memories WHERE simhash = ? AND tags LIKE ?",
            (simhash, f"%{primary_tag}%"),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except sqlite3.Error:
        pass

    return None


def enforce_budget(primary_tag):
    budget = BUDGETS.get(primary_tag)
    if budget is None:
        return 0

    try:
        conn = sqlite3.connect(OM_DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM memories WHERE tags LIKE ?",
            (f"%{primary_tag}%",),
        )
        count = cursor.fetchone()[0]

        if count < budget:
            conn.close()
            return 0

        now = time.time()
        cursor.execute(
            "SELECT id, feedback_score, decay_lambda, created_at FROM memories WHERE tags LIKE ?",
            (f"%{primary_tag}%",),
        )
        entries = []
        for row_id, score, decay, created_at in cursor.fetchall():
            age_days = (now - (created_at or now)) / 86400.0
            lam = decay if decay else DEFAULT_DECAY
            weighted = (score if score else 0.0) * math.exp(-lam * age_days)
            entries.append((row_id, weighted))

        entries.sort(key=lambda x: x[1])
        to_delete = count - budget + 1
        deleted = 0
        for row_id, _ in entries[:to_delete]:
            cursor.execute("DELETE FROM memories WHERE id = ?", (row_id,))
            deleted += 1

        conn.commit()
        conn.close()
        return deleted
    except sqlite3.Error:
        return 0


def prune_expired(threshold=PRUNE_THRESHOLD):
    try:
        conn = sqlite3.connect(OM_DB_PATH, timeout=10)
        cursor = conn.cursor()
        now = time.time()

        cursor.execute("SELECT id, feedback_score, decay_lambda, created_at FROM memories")
        to_delete = []
        for row_id, score, decay, created_at in cursor.fetchall():
            age_days = (now - (created_at or now)) / 86400.0
            lam = decay if decay else DEFAULT_DECAY
            weighted = (score if score else 0.0) * math.exp(-lam * age_days)
            if weighted < threshold:
                to_delete.append(row_id)

        for row_id in to_delete:
            cursor.execute("DELETE FROM memories WHERE id = ?", (row_id,))

        conn.commit()
        conn.close()
        _log_op("pruning_ran", {"deleted": len(to_delete), "threshold": threshold})
        return len(to_delete)
    except sqlite3.Error as e:
        _log_op("prune_error", {"error": str(e)})
        return 0


def om_write(content, tags, user_id="proj:dotclaude", sector="procedural",
             salience=0.5, decay_lambda=0.05):
    valid_tags = [t for t in tags if t in ALLOWED_TAGS]
    if not valid_tags:
        _log_op("write_rejected", {"tags": tags, "reason": "no allowed tags"})
        return None

    primary_tag = valid_tags[0]

    try:
        existing_id = dedup_check(content, primary_tag)
        if existing_id is not None:
            now = int(time.time())
            conn = sqlite3.connect(OM_DB_PATH, timeout=10)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE memories SET content = ?, updated_at = ?, last_seen_at = ? WHERE id = ?",
                (content, now, now, existing_id),
            )
            conn.commit()
            conn.close()
            _log_op("dedup_fired", {"existing_id": existing_id, "primary_tag": primary_tag})
            return existing_id

        pruned = enforce_budget(primary_tag)
        if pruned > 0:
            _log_op("budget_enforced", {"primary_tag": primary_tag, "pruned": pruned})

        embedding = _get_embedding(content)
        now = int(time.time())
        new_id = str(uuid.uuid4())

        if embedding is not None:
            mean_vec = _embedding_to_blob(embedding)
            mean_dim = len(embedding)
            simhash = _compute_simhash(content)
        else:
            mean_vec = None
            mean_dim = None
            simhash = _compute_simhash(content)

        tags_json = json.dumps(tags)

        conn = sqlite3.connect(OM_DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memories (id, user_id, content, simhash, primary_sector, tags, "
            "mean_dim, mean_vec, created_at, updated_at, last_seen_at, salience, "
            "decay_lambda, feedback_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, user_id, content, simhash, sector, tags_json,
             mean_dim, mean_vec, now, now, now, salience,
             decay_lambda, salience),
        )
        conn.commit()
        conn.close()

        _log_op("write_success", {"id": new_id, "primary_tag": primary_tag})
        return new_id

    except Exception as e:
        _log_op("write_error", {"error": str(e), "tags": tags})
        return None
