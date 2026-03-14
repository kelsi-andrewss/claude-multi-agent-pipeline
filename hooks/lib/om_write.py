#!/usr/bin/env python3
"""Centralized OpenMemory write gate.

All OM writes should go through om_write() to enforce tag whitelist,
dedup, budget limits, and stderr logging.
"""
import hashlib, json, math, os, sqlite3, sys, time, uuid
from datetime import datetime, timezone

from hooks.lib.embedding_utils import get_embedding, cosine_similarity, embedding_to_blob, blob_to_embedding

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
DEDUP_THRESHOLD = 0.85
PRUNE_THRESHOLD = 0.01
DEFAULT_DECAY = 0.05


def _compute_simhash(content):
    return hashlib.md5(content.lower().strip().encode()).hexdigest()[:16]


def dedup_check(content, primary_tag):
    embedding = get_embedding(content)

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
                stored_vec = blob_to_embedding(blob)
                sim = cosine_similarity(embedding, stored_vec)
                if sim >= DEDUP_THRESHOLD:
                    return row_id
        except sqlite3.Error:
            pass
        return None

    print("om_write: ollama_fallback — embedding unavailable for dedup", file=sys.stderr)
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
        print(f"om_write: pruning_ran — deleted={len(to_delete)} threshold={threshold}", file=sys.stderr)
        return len(to_delete)
    except sqlite3.Error as e:
        print(f"om_write: prune_error — {e}", file=sys.stderr)
        return 0


def om_write(content, tags, user_id="proj:dotclaude", sector="procedural",
             salience=0.5, decay_lambda=0.05):
    valid_tags = [t for t in tags if t in ALLOWED_TAGS]
    if not valid_tags:
        print(f"om_write: write_rejected — tags={tags} reason=no allowed tags", file=sys.stderr)
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
            print(f"om_write: dedup_fired — existing_id={existing_id} primary_tag={primary_tag}", file=sys.stderr)
            return existing_id

        pruned = enforce_budget(primary_tag)
        if pruned > 0:
            print(f"om_write: budget_enforced — primary_tag={primary_tag} pruned={pruned}", file=sys.stderr)

        embedding = get_embedding(content)
        now = int(time.time())
        new_id = str(uuid.uuid4())

        if embedding is not None:
            mean_vec = embedding_to_blob(embedding)
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

        print(f"om_write: write_success — id={new_id} primary_tag={primary_tag}", file=sys.stderr)
        return new_id

    except Exception as e:
        print(f"om_write: write_error — error={e} tags={tags}", file=sys.stderr)
        return None
