#!/usr/bin/env python3
"""Signal processor: correlate user corrections with recorded decision preferences.

Usage: signal_processor.py <transcript_path> <epics_db_path> [session_id]

Reads the session transcript, identifies corrections via semantic embedding,
matches them against decision_preferences, and updates signal_score/signal_count.
Manual corrections are written directly to correction_groups via log-correction.sh.
"""
import json, os, re, sqlite3, sys, time

from hooks.lib.embedding_utils import get_embedding, cosine_similarity, embedding_to_blob, blob_to_embedding


def parse_transcript_turns(transcript_path):
    lines = []
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if len(lines) > 5000:
        lines = lines[-2000:]

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
            turns.append({"role": role, "content": content_text.strip(), "turn_idx": len(turns), "has_tool_use": has_tool_use})

    return turns


SYSTEM_MSG = re.compile(
    r'<(local-command-caveat|task-notification|system-reminder|command-name|command-message)>|'
    r'^Base directory for this skill|'
    r'^Implement the following plan:|'
    r'^<skill-',
    re.IGNORECASE
)

POSITIVE_INTENT = re.compile(
    r"^(let'?s |looks good|ship it|continue|approved|woo+|yes[,.\s!]|yeah|okay|lgtm|"
    r"go ahead|do it|hell yeah|let'?s go|nice|perfect|awesome|sounds good|love it|great|cool)",
    re.IGNORECASE
)

def is_structural_content(msg):
    """Pre-filter: returns True if message is structural/pasted content that should
    be rejected before embedding. Catches code fences, long messages, markdown
    headers, timestamps, and URL-heavy pastes."""
    if len(msg) > 300:
        return True
    if "```" in msg or "~~~" in msg:
        return True
    if msg.count("\n") > 3:
        return True
    if re.search(r"^#{1,6}\s", msg, re.MULTILINE):
        return True
    if re.search(r"\[\d{1,2}:\d{2}\s*[AP]M\]", msg):
        return True
    if len(re.findall(r"https?://", msg)) >= 3:
        return True
    return False


def extract_corrections(turns):
    """Extract user corrections using structural pre-filter + semantic delta.

    Returns list of dicts: {turn_idx, content, weight}
    Weight: 1.0 normal, 3.0 repeated (same correction theme twice+).
    Returns empty list if Ollama is unavailable (no regex fallback).
    """
    prototype_embs = _get_prototype_embeddings()
    if prototype_embs is None:
        return []

    corrections = []
    seen_themes = {}
    prev_assistant_had_tool_use = False
    embedding_calls = 0

    for i, turn in enumerate(turns):
        if turn["role"] == "assistant":
            prev_assistant_had_tool_use = turn.get("has_tool_use", False)
            continue
        if turn["role"] != "user":
            continue

        msg = turn["content"]
        if SYSTEM_MSG.search(msg):
            prev_assistant_had_tool_use = False
            continue
        if POSITIVE_INTENT.match(msg):
            prev_assistant_had_tool_use = False
            continue
        if is_structural_content(msg):
            prev_assistant_had_tool_use = False
            continue

        if embedding_calls < MAX_EMBEDDING_CALLS_PER_SESSION:
            embedding_calls += 1
            matched = is_correction(msg, prototype_embs)
        else:
            matched = False

        if matched:
            theme_key = msg[:30].lower().strip()
            weight = 1.0

            if theme_key in seen_themes:
                weight = 3.0
            seen_themes[theme_key] = True

            corrections.append({
                "turn_idx": turn["turn_idx"],
                "content": msg[:300],
                "weight": weight,
            })

        prev_assistant_had_tool_use = False

    return corrections


def extract_corrections_from_transcript(transcript_path):
    """Load transcript file, parse turns, extract corrections.

    Combines parse_transcript_turns() and extract_corrections() into a single
    file-path-in, corrections-out call. All filtering (SYSTEM_MSG, POSITIVE_INTENT,
    structural pre-filter) is applied via extract_corrections().

    Args:
        transcript_path: Path to JSONL transcript file.

    Returns:
        List of correction dicts: [{"turn_idx": int, "content": str, "weight": float}]
        Returns empty list on file errors or when no corrections found.
    """
    try:
        turns = parse_transcript_turns(transcript_path)
    except (OSError, IOError):
        return []
    if not turns:
        return []
    return extract_corrections(turns)


def text_overlap(text_a, text_b):
    """Simple word-overlap similarity between two texts."""
    words_a = set(re.findall(r'\w{3,}', text_a.lower()))
    words_b = set(re.findall(r'\w{3,}', text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / min(len(words_a), len(words_b))


def match_correction_to_decisions(correction, decisions, turns):
    """Try to match a correction to a decision.

    Matching criteria:
    - Text similarity: correction references decision context or chosen_path
    - Temporal proximity: correction within 3 turns of decision-related content

    Returns matched decision id or None.
    """
    best_match = None
    best_score = 0.0

    correction_idx = correction["turn_idx"]
    correction_text = correction["content"]

    for dec in decisions:
        score = 0.0

        context_overlap = text_overlap(correction_text, dec["context"])
        path_overlap = text_overlap(correction_text, dec["chosen_path"])
        score = max(context_overlap, path_overlap)

        if dec.get("mention_turn_idx") is not None:
            turn_distance = abs(correction_idx - dec["mention_turn_idx"])
            if turn_distance <= 3:
                score += 0.3 * (1.0 - turn_distance / 3.0)

        if score > best_score and score >= 0.15:
            best_score = score
            best_match = dec["id"]

    return best_match


def find_decision_mention_turns(decisions, turns):
    """Scan assistant turns for mentions of decision context/chosen_path."""
    for dec in decisions:
        dec["mention_turn_idx"] = None
        context_words = set(re.findall(r'\w{4,}', dec["context"].lower()))
        path_words = set(re.findall(r'\w{4,}', dec["chosen_path"].lower()))
        key_words = context_words | path_words

        if not key_words:
            continue

        for turn in turns:
            if turn["role"] != "assistant":
                continue
            turn_words = set(re.findall(r'\w{4,}', turn["content"].lower()))
            overlap = key_words & turn_words
            if len(overlap) >= 2:
                dec["mention_turn_idx"] = turn["turn_idx"]
                break


SIMILARITY_THRESHOLD = 0.85
PROMOTION_THRESHOLD = 3

CORRECTION_PROTOTYPES = [
    "stop doing that, I told you not to",
    "why did you ignore my instruction",
    "use the ship skill instead",
    "you keep making the same mistake",
    "that's wrong, do it this way instead",
    "why aren't you using worktrees",
    "I already told you to log that",
    "don't narrate what you're about to do",
    "why did you skip the pipeline",
    "you're not listening to me",
]
PROTOTYPE_THRESHOLD = 0.55
MAX_EMBEDDING_CALLS_PER_SESSION = 5
_prototype_embeddings = None


def _get_prototype_embeddings():
    """Lazy-load and cache prototype embeddings. Returns None if Ollama unavailable."""
    global _prototype_embeddings
    if _prototype_embeddings is not None:
        return _prototype_embeddings
    embeddings = []
    for proto in CORRECTION_PROTOTYPES:
        vec = get_embedding(proto)
        if vec is None:
            return None
        embeddings.append(vec)
    _prototype_embeddings = embeddings
    return _prototype_embeddings


def is_correction(msg, prototype_embeddings):
    """Returns True if msg is semantically similar to a correction prototype.

    Computes cosine similarity against each prototype embedding and returns
    True if max similarity >= PROTOTYPE_THRESHOLD.
    """
    msg_vec = get_embedding(msg)
    if msg_vec is None:
        return False
    similarities = [cosine_similarity(msg_vec, proto_vec) for proto_vec in prototype_embeddings]
    return max(similarities) >= PROTOTYPE_THRESHOLD


def _ensure_correction_groups_table(cursor):
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS correction_groups ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "theme TEXT NOT NULL, "
        "status TEXT DEFAULT 'accumulating' CHECK(status IN ('accumulating','pending_promotion','promoted','dismissed')), "
        "count INTEGER DEFAULT 1, "
        "correction_dates TEXT DEFAULT '[]', "
        "embedding BLOB, "
        "promoted_at TEXT, "
        "created_at INTEGER, "
        "updated_at INTEGER, "
        "source TEXT DEFAULT 'auto', "
        "text TEXT DEFAULT '')"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_correction_groups_status ON correction_groups(status)"
    )


def _find_matching_group(cursor, embedding, threshold):
    cursor.execute("SELECT id, embedding FROM correction_groups WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()
    best_id = None
    best_sim = threshold
    for row in rows:
        stored_vec = blob_to_embedding(row[1])
        sim = cosine_similarity(embedding, stored_vec)
        if sim > best_sim:
            best_sim = sim
            best_id = row[0]
    return best_id


def _check_promoted(theme_text, project_root):
    """Check if theme is already promoted in correction_groups DB."""
    db_path = os.path.join(project_root, ".claude", "epics.db")
    if not os.path.isfile(db_path):
        return False

    try:
        conn = sqlite3.connect(db_path, timeout=5)
        rows = conn.execute(
            "SELECT theme FROM correction_groups WHERE status='promoted'"
        ).fetchall()
        conn.close()
    except Exception:
        return False

    if not rows:
        return False

    theme_vec = get_embedding(theme_text)
    if theme_vec is None:
        return False

    for (existing_theme,) in rows:
        existing_vec = get_embedding(existing_theme)
        if existing_vec is None:
            continue
        if cosine_similarity(theme_vec, existing_vec) > 0.8:
            return True

    return False


def process_session_corrections(transcript_path, db_file, session_id="", project_root=None):
    """Unified entry point: detect corrections from transcript and upsert to correction_groups.

    Handles:
    1. Transcript-based correction detection (pre-filter + semantic delta)
    2. Per-session rate limiting: max 1 DB increment per theme per session

    Args:
        transcript_path: Path to JSONL transcript file.
        db_file: Path to epics.db.
        session_id: Session identifier (used for rate-limiting log, not DB key).
        project_root: Root of the dotclaude project (defaults to grandparent of db_file).

    Returns:
        List of correction dicts: [{"turn_idx": int, "content": str, "weight": float}]
    """
    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(db_file))

    all_corrections = []
    seen_themes = set()

    # --- Part 1: Transcript-based detection ---
    transcript_corrections = extract_corrections_from_transcript(transcript_path)
    all_corrections.extend(transcript_corrections)

    # Manual corrections now written directly to correction_groups via log-correction.sh
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Part 3: Upsert to correction_groups with per-session rate limiting ---
    if not db_file or not os.path.isfile(db_file):
        return all_corrections

    try:
        conn = sqlite3.connect(db_file, timeout=10)
        cursor = conn.cursor()
        _ensure_correction_groups_table(cursor)
        now = int(time.time())

        grouping_embedding_calls = 0

        for correction in all_corrections:
            theme_text = correction["content"]
            theme_key = theme_text[:300]

            # Per-session rate limit: skip DB increment if theme already seen this session
            if theme_key in seen_themes:
                continue
            seen_themes.add(theme_key)

            # Try semantic matching via embedding before falling back to exact text match
            matched_group_id = None
            correction_embedding = None
            if grouping_embedding_calls < MAX_EMBEDDING_CALLS_PER_SESSION:
                grouping_embedding_calls += 1
                correction_embedding = get_embedding(theme_key)
                if correction_embedding is not None:
                    matched_group_id = _find_matching_group(cursor, correction_embedding, SIMILARITY_THRESHOLD)

            if matched_group_id is not None:
                # Semantic match found -- use that group for the update
                row = cursor.execute(
                    "SELECT id, count, correction_dates, status FROM correction_groups WHERE id = ?",
                    (matched_group_id,)
                ).fetchone()
            else:
                # Fallback: exact text prefix match (original behavior)
                row = cursor.execute(
                    "SELECT id, count, correction_dates, status FROM correction_groups "
                    "WHERE theme = ?",
                    (theme_key,)
                ).fetchone()

            if row:
                if row[3] in ('promoted', 'dismissed'):
                    continue
                new_count = row[1] + 1
                old_dates = json.loads(row[2]) if row[2] else []
                old_dates.append(today)
                new_status = 'pending_promotion' if new_count >= PROMOTION_THRESHOLD else row[3]
                cursor.execute(
                    "UPDATE correction_groups SET count=?, correction_dates=?, status=?, updated_at=? WHERE id=?",
                    (new_count, json.dumps(old_dates), new_status, now, row[0])
                )
            else:
                embedding_blob = embedding_to_blob(correction_embedding) if correction_embedding is not None else None
                cursor.execute(
                    "INSERT INTO correction_groups (theme, status, count, correction_dates, embedding, source, created_at, updated_at) "
                    "VALUES (?, 'accumulating', 1, ?, ?, 'auto', ?, ?)",
                    (theme_text[:300], json.dumps([today]), embedding_blob, now, now)
                )

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"process_session_corrections DB error: {e}", file=sys.stderr)

    return all_corrections


def get_domain_success_rates(db_path):
    """Query merge_outcomes for per-domain success rates.

    Parses domain_tags JSON array per row, accumulates per-domain success/total counts.
    Returns dict of {domain: success_rate}. Empty dict if table missing or no records.
    """
    if not os.path.isfile(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='merge_outcomes'"
        )
        if not cursor.fetchone():
            conn.close()
            return {}
        rows = cursor.execute(
            "SELECT domain_tags, success FROM merge_outcomes WHERE success IS NOT NULL"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return {}

    domain_counts = {}
    for domain_tags_json, success in rows:
        try:
            tags = json.loads(domain_tags_json) if domain_tags_json else []
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            if tag not in domain_counts:
                domain_counts[tag] = {"success": 0, "total": 0}
            domain_counts[tag]["total"] += 1
            if success:
                domain_counts[tag]["success"] += 1

    return {
        domain: counts["success"] / counts["total"]
        for domain, counts in domain_counts.items()
        if counts["total"] > 0
    }


def get_model_success_rates(db_path):
    """Query merge_outcomes grouped by model for per-model success rates.

    Returns dict of {model: success_rate}. Empty dict if table missing or no records.
    """
    if not os.path.isfile(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='merge_outcomes'"
        )
        if not cursor.fetchone():
            conn.close()
            return {}
        rows = cursor.execute(
            "SELECT model, COUNT(*) as total, SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes "
            "FROM merge_outcomes WHERE success IS NOT NULL AND model IS NOT NULL "
            "GROUP BY model"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return {}

    return {
        model: successes / total
        for model, total, successes in rows
        if total > 0
    }


def feed_outcomes_to_scoring(db_path):
    """Aggregate domain and model success rates for trust calibration.

    Calls get_domain_success_rates and get_model_success_rates, logs warnings
    for models with success_rate < 0.7 and sample_count >= 5.

    Returns {"domain_rates": dict, "model_rates": dict}.
    """
    domain_rates = get_domain_success_rates(db_path)
    model_rates = get_model_success_rates(db_path)

    if os.path.isfile(db_path):
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            rows = conn.execute(
                "SELECT model, COUNT(*) as total, SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes "
                "FROM merge_outcomes WHERE success IS NOT NULL AND model IS NOT NULL "
                "GROUP BY model"
            ).fetchall()
            conn.close()
            for model, total, successes in rows:
                if total >= 5 and (successes / total) < 0.7:
                    print(
                        f"Warning: model '{model}' success rate {successes/total:.1%} "
                        f"({successes}/{total}) below 0.7 threshold",
                        file=sys.stderr,
                    )
        except sqlite3.Error:
            pass

    return {"domain_rates": domain_rates, "model_rates": model_rates}


def compute_trust_scores(db_path):
    """Compute global and per-domain trust scores from merge_outcomes.

    Opens run-state.db at db_path, queries merge_outcomes for all records
    with success IS NOT NULL. Global score = success_count / total_count
    (default 0.5 if no records). Per-domain: parse domain_tags JSON array
    per row, group by tag, compute score. Mark domain as override when
    domain_score < global_score - 0.15 AND domain_count >= 3.

    Returns: {"global": float, "domains": {name: {"score": float, "count": int,
              "override": bool}}, "sample_count": int}
    """
    if not os.path.isfile(db_path):
        return {"global": 0.5, "domains": {}, "sample_count": 0}
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='merge_outcomes'"
        )
        if not cursor.fetchone():
            conn.close()
            return {"global": 0.5, "domains": {}, "sample_count": 0}
        rows = cursor.execute(
            "SELECT domain_tags, success FROM merge_outcomes WHERE success IS NOT NULL"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return {"global": 0.5, "domains": {}, "sample_count": 0}

    if not rows:
        return {"global": 0.5, "domains": {}, "sample_count": 0}

    # Global score
    total_count = len(rows)
    success_count = sum(1 for _, success in rows if success)
    global_score = success_count / total_count

    # Per-domain scores
    domain_counts = {}
    for domain_tags_json, success in rows:
        try:
            tags = json.loads(domain_tags_json) if domain_tags_json else []
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            if tag not in domain_counts:
                domain_counts[tag] = {"success": 0, "total": 0}
            domain_counts[tag]["total"] += 1
            if success:
                domain_counts[tag]["success"] += 1

    domains = {}
    for domain, counts in domain_counts.items():
        if counts["total"] == 0:
            continue
        domain_score = counts["success"] / counts["total"]
        override = domain_score < global_score - 0.15 and counts["total"] >= 3
        domains[domain] = {
            "score": domain_score,
            "count": counts["total"],
            "override": override,
        }

    return {"global": global_score, "domains": domains, "sample_count": total_count}


def get_trust_level(trust_report, domain=None):
    """Determine trust level from a trust report.

    If domain provided and domain has override: use min(global, domain_score).
    Otherwise: use global score.

    Returns "high" (>= 0.85), "medium" (>= 0.70), "low" (< 0.70).
    """
    score = trust_report["global"]

    if domain and domain in trust_report.get("domains", {}):
        domain_info = trust_report["domains"][domain]
        if domain_info.get("override"):
            score = min(score, domain_info["score"])

    if score >= 0.85:
        return "high"
    elif score >= 0.70:
        return "medium"
    else:
        return "low"


def recommend_model(trust_level, agent, file_count):
    """Recommend model based on trust level, agent type, and file count.

    - "high" + agent=="quick-fixer" + file_count==1: return "haiku"
    - "high" or "medium": return "sonnet"
    - "low": return "sonnet" (escalation threshold 1 not 2)

    Returns model string.
    """
    if trust_level == "high" and agent == "quick-fixer" and file_count == 1:
        return "haiku"
    return "sonnet"


def main_logic(transcript_path, db_path, session_id=""):
    """Core signal processing: correlate corrections with decision_preferences.

    Performs:
    1. Connect to db_path, query recent decision_preferences
    2. Parse transcript turns, find decision mention turns
    3. Run process_session_corrections (correction detection + DB upsert)
    4. For matched corrections: decrement signal_score by correction weight
    5. For unmatched decisions: increment signal_score by 0.5 (implicit approval)
    6. Commit and close

    Args:
        transcript_path: Path to JSONL transcript file.
        db_path: Path to epics.db.
        session_id: Session identifier for filtering decisions.

    Returns:
        None. Side effects: updates decision_preferences.signal_score/signal_count
        in db_path, upserts correction_groups via process_session_corrections.

    Exits silently (returns None) when:
        - transcript_path or db_path don't exist
        - decision_preferences table missing
        - No recent decisions found
        - No transcript turns parsed
    """
    if not os.path.isfile(transcript_path) or not os.path.isfile(db_path):
        return

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='decision_preferences'"
        )
        if not cursor.fetchone():
            conn.close()
            return
    except Exception:
        return

    now = int(time.time())
    day_ago = now - 86400

    try:
        if session_id:
            cursor.execute(
                "SELECT id, decision_type, context, chosen_path, session_id "
                "FROM decision_preferences "
                "WHERE session_id = ? OR created_at >= ?",
                (session_id, day_ago),
            )
        else:
            cursor.execute(
                "SELECT id, decision_type, context, chosen_path, session_id "
                "FROM decision_preferences "
                "WHERE created_at >= ?",
                (day_ago,),
            )
        decisions = [dict(row) for row in cursor.fetchall()]
    except Exception:
        conn.close()
        return

    if not decisions:
        conn.close()
        return

    turns = parse_transcript_turns(transcript_path)
    if not turns:
        conn.close()
        return

    find_decision_mention_turns(decisions, turns)

    project_root = os.path.dirname(os.path.dirname(db_path))
    corrections = process_session_corrections(transcript_path, db_path, session_id, project_root)

    matched_decision_ids = set()

    for correction in corrections:
        matched_id = match_correction_to_decisions(correction, decisions, turns)
        if matched_id:
            matched_decision_ids.add(matched_id)
            weight = correction["weight"]
            try:
                cursor.execute(
                    "UPDATE decision_preferences "
                    "SET signal_score = signal_score - ?, signal_count = signal_count + 1, updated_at = ? "
                    "WHERE id = ?",
                    (weight, now, matched_id),
                )
                print(
                    f"Signal: decision {matched_id} score -= {weight} "
                    f"(correction: {correction['content'][:60]}...)",
                    file=sys.stderr,
                )
            except Exception as e:
                print(f"Signal update failed for {matched_id}: {e}", file=sys.stderr)

    for dec in decisions:
        if dec["id"] not in matched_decision_ids:
            try:
                cursor.execute(
                    "UPDATE decision_preferences "
                    "SET signal_score = signal_score + 0.5, signal_count = signal_count + 1, updated_at = ? "
                    "WHERE id = ?",
                    (now, dec["id"]),
                )
                print(
                    f"Signal: decision {dec['id']} score += 0.5 (implicit approval)",
                    file=sys.stderr,
                )
            except Exception as e:
                print(f"Signal update failed for {dec['id']}: {e}", file=sys.stderr)

    conn.commit()
    conn.close()


def main():
    if len(sys.argv) < 3:
        print("Usage: signal_processor.py <transcript_path> <epics_db_path> [session_id]", file=sys.stderr)
        sys.exit(1)

    transcript_path = sys.argv[1]
    db_path = sys.argv[2]
    session_id = sys.argv[3] if len(sys.argv) > 3 else ""
    main_logic(transcript_path, db_path, session_id)


if __name__ == "__main__":
    main()
