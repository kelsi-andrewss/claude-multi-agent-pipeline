#!/usr/bin/env python3
"""Centralized OpenMemory write gate.

All OM writes should go through om_write() to enforce tag whitelist,
dedup, budget limits, and stderr logging.
"""
import hashlib, json, math, os, sqlite3, sys, time, uuid
from contextlib import contextmanager
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

_ollama_fallback_warned = False
_migration_done = False


@contextmanager
def _db_connection():
    conn = sqlite3.connect(OM_DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_primary_tag_column():
    global _migration_done
    if _migration_done:
        return
    try:
        with _db_connection() as conn:
            cursor = conn.cursor()
            cols = {row[1] for row in cursor.execute("PRAGMA table_info(memories)").fetchall()}
            if "primary_tag" not in cols:
                cursor.execute("ALTER TABLE memories ADD COLUMN primary_tag TEXT")
                cursor.execute("UPDATE memories SET primary_tag = json_extract(tags, '$[0]') WHERE primary_tag IS NULL")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_primary_tag ON memories(primary_tag)")
                conn.commit()
            else:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_primary_tag ON memories(primary_tag)")
                conn.commit()
        _migration_done = True
    except sqlite3.Error:
        _migration_done = True


def _content_hash(content):
    return hashlib.md5(content.lower().strip().encode()).hexdigest()[:16]


def dedup_check(content, primary_tag, conn=None):
    """Returns (existing_id or None, embedding or None).

    When conn is provided, uses that connection (caller owns lifecycle).
    When conn is None, opens its own connection for backward compat.
    """
    _ensure_primary_tag_column()
    embedding = get_embedding(content)

    if embedding is not None:
        try:
            _conn = conn if conn is not None else sqlite3.connect(OM_DB_PATH, timeout=10)
            try:
                cursor = _conn.cursor()
                cursor.execute(
                    "SELECT id, mean_vec FROM memories WHERE primary_tag = ? AND mean_vec IS NOT NULL",
                    (primary_tag,),
                )
                rows = cursor.fetchall()

                for row_id, blob in rows:
                    stored_vec = blob_to_embedding(blob)
                    sim = cosine_similarity(embedding, stored_vec)
                    if sim >= DEDUP_THRESHOLD:
                        return row_id, embedding
            finally:
                if conn is None:
                    _conn.close()
        except sqlite3.Error:
            pass
        return None, embedding

    global _ollama_fallback_warned
    if not _ollama_fallback_warned:
        print("om_write: ollama_fallback — embedding unavailable for dedup", file=sys.stderr)
        _ollama_fallback_warned = True
    simhash = _content_hash(content)
    try:
        _conn = conn if conn is not None else sqlite3.connect(OM_DB_PATH, timeout=10)
        try:
            cursor = _conn.cursor()
            cursor.execute(
                "SELECT id FROM memories WHERE simhash = ? AND primary_tag = ?",
                (simhash, primary_tag),
            )
            row = cursor.fetchone()
            if row:
                return row[0], None
        finally:
            if conn is None:
                _conn.close()
    except sqlite3.Error:
        pass

    return None, None


def enforce_budget(conn, primary_tag):
    """Delete oldest entries to make room. Uses caller-provided connection.
    Does NOT commit — caller is responsible for committing."""
    budget = BUDGETS.get(primary_tag)
    if budget is None:
        return 0

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM memories WHERE primary_tag = ?",
            (primary_tag,),
        )
        count = cursor.fetchone()[0]

        if count < budget:
            return 0

        now = time.time()
        cursor.execute(
            "SELECT id, feedback_score, decay_lambda, created_at FROM memories WHERE primary_tag = ?",
            (primary_tag,),
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

        return deleted
    except sqlite3.Error:
        return 0


def prune_expired(threshold=PRUNE_THRESHOLD):
    try:
        with _db_connection() as conn:
            cursor = conn.cursor()
            now = time.time()

            cursor.execute("SELECT id, feedback_score, decay_lambda, created_at FROM memories")
            to_delete = []
            for row_id, score, decay, created_at in cursor.fetchall():
                if score is None or score == 0:
                    continue
                age_days = (now - (created_at or now)) / 86400.0
                lam = decay if decay else DEFAULT_DECAY
                weighted = score * math.exp(-lam * age_days)
                if weighted < threshold:
                    to_delete.append(row_id)

            for row_id in to_delete:
                cursor.execute("DELETE FROM memories WHERE id = ?", (row_id,))

            conn.commit()
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
        with _db_connection() as conn:
            existing_id, embedding = dedup_check(content, primary_tag, conn=conn)
            if existing_id is not None:
                now = int(time.time())
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE memories SET content = ?, updated_at = ?, last_seen_at = ? WHERE id = ?",
                    (content, now, now, existing_id),
                )
                conn.commit()
                print(f"om_write: dedup_fired — existing_id={existing_id} primary_tag={primary_tag}", file=sys.stderr)
                return existing_id

            now = int(time.time())
            new_id = str(uuid.uuid4())

            if embedding is not None:
                mean_vec = embedding_to_blob(embedding)
                mean_dim = len(embedding)
            else:
                mean_vec = None
                mean_dim = None

            simhash = _content_hash(content)
            tags_json = json.dumps(tags)

            pruned = enforce_budget(conn, primary_tag)
            if pruned > 0:
                print(f"om_write: budget_enforced — primary_tag={primary_tag} pruned={pruned}", file=sys.stderr)

            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO memories (id, user_id, content, simhash, primary_sector, tags, "
                "primary_tag, mean_dim, mean_vec, created_at, updated_at, last_seen_at, salience, "
                "decay_lambda, feedback_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id, user_id, content, simhash, sector, tags_json,
                 primary_tag, mean_dim, mean_vec, now, now, now, salience,
                 decay_lambda, salience),
            )
            conn.commit()

            print(f"om_write: write_success — id={new_id} primary_tag={primary_tag}", file=sys.stderr)
            return new_id

    except Exception as e:
        print(f"om_write: write_error — error={e} tags={tags}", file=sys.stderr)
        return None
