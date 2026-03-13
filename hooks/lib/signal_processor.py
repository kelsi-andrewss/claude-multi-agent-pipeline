#!/usr/bin/env python3
"""Signal processor: correlate user corrections with recorded decision preferences.

Usage: signal_processor.py <transcript_path> <epics_db_path> <session_id>

Reads the session transcript, identifies corrections, matches them against
decision_preferences from the current session or last 24 hours, and updates
signal_score/signal_count accordingly.
"""
import hashlib, json, math, os, re, sqlite3, struct, sys, time, uuid
from urllib.request import urlopen, Request
from urllib.error import URLError


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


IMPERATIVE_STARTS = re.compile(
    r'^(use |stop |don\'t |do not |just |why didn\'t |why don\'t |why aren\'t |'
    r'make |run |try |ship |log |fix |check |read |write |call |add |remove |'
    r'never |always )',
    re.IGNORECASE
)

META_PATTERN = re.compile(
    r"you'?ve been |you'?re not |you keep |you should |you always |you never ",
    re.IGNORECASE
)

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

EXTERNAL_CONTENT = re.compile(
    r'^\w[\w\s]{0,30}\s+\[\d{1,2}:\d{2}\s*[AP]M\]|'  # Slack: "Username  [9:52 PM]"
    r'\[\d{1,2}:\d{2}\s*[AP]M\]|'                       # Bare timestamp: "[9:52 PM]"
    r'This session is being continued|'                   # Exact continuation
    r'session.*continued from|'                           # Variant continuations
    r'continued from previous|'                           # Variant continuations
    r'^(~~~|```)',                                         # Code fence starts
    re.MULTILINE
)


def is_frustration(msg):
    if len(msg) > 200:
        return False
    if msg.rstrip().endswith("!!") or msg.rstrip().endswith("??"):
        return True
    caps_words = [w for w in msg.split() if w.isupper() and len(w) > 1]
    return len(caps_words) >= 2


def extract_corrections(turns):
    """Extract user corrections with intensity weights.

    Returns list of dicts: {turn_idx, content, weight}
    Weight: 1.0 normal, 2.0 frustration, 3.0 repeated (same correction theme twice+)
    """
    corrections = []
    seen_themes = {}
    prev_assistant_had_tool_use = False

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
        if EXTERNAL_CONTENT.search(msg):
            prev_assistant_had_tool_use = False
            continue

        matched = False

        if len(msg) < 150 and prev_assistant_had_tool_use and IMPERATIVE_STARTS.match(msg):
            matched = True
        if not matched and prev_assistant_had_tool_use and is_frustration(msg):
            matched = True
        if not matched and META_PATTERN.search(msg):
            matched = True

        if matched:
            theme_key = msg[:30].lower().strip()
            weight = 1.0

            if is_frustration(msg):
                weight = 2.0

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
    EXTERNAL_CONTENT) is applied via extract_corrections().

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


OLLAMA_URL = "http://localhost:11434/api/embeddings"
OLLAMA_MODEL = "nomic-embed-text"
SIMILARITY_THRESHOLD = 0.85
PROMOTION_THRESHOLD = 3


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


def _parse_corrections(project_root):
    corrections_path = os.path.join(project_root, "corrections.md")
    if not os.path.isfile(corrections_path):
        return []

    with open(corrections_path) as f:
        text = f.read()

    tallies = {}
    tallies_path = os.path.join(project_root, "correction-tallies.jsonl")
    if os.path.isfile(tallies_path):
        with open(tallies_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("promoted"):
                        tallies[entry.get("header", "")] = True
                except json.JSONDecodeError:
                    continue

    entries = []
    sections = re.split(r'^## ', text, flags=re.MULTILINE)
    for section in sections:
        section = section.strip()
        if not section:
            continue

        lines = section.split('\n', 1)
        header_line = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""

        # Skip non-correction sections (file header, format notes)
        date_match = re.match(r'^(\d{4}-\d{2}-\d{2})', header_line)
        if not date_match:
            continue

        if header_line.startswith("AUTO:") and header_line in tallies:
            continue

        date = date_match.group(1)
        header = header_line[:80]

        if body or header:
            entries.append({"date": date, "header": header, "body": (header + "\n" + body)[:1000]})

    return entries


def _cosine_similarity(vec_a, vec_b):
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _find_matching_group(cursor, embedding, threshold):
    cursor.execute("SELECT id, embedding FROM correction_groups WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()
    best_id = None
    best_sim = threshold
    for row in rows:
        stored_vec = _blob_to_embedding(row[1])
        sim = _cosine_similarity(embedding, stored_vec)
        if sim > best_sim:
            best_sim = sim
            best_id = row[0]
    return best_id


def _check_promoted(theme_text, project_root):
    prefs_path = os.path.join(project_root, "behavioral-prefs.md")
    if not os.path.isfile(prefs_path):
        return False

    with open(prefs_path) as f:
        text = f.read()

    pref_lines = [line.strip()[2:] for line in text.split('\n') if line.strip().startswith('- ')]
    if not pref_lines:
        return False

    theme_vec = _get_embedding(theme_text)
    if theme_vec is None:
        return False

    for pref_line in pref_lines:
        pref_vec = _get_embedding(pref_line)
        if pref_vec is None:
            continue
        if _cosine_similarity(theme_vec, pref_vec) > 0.8:
            return True

    return False


def _process_correction_groups(db_path, project_root):
    entries = _parse_corrections(project_root)
    if not entries:
        return

    first_vec = _get_embedding(entries[0]["body"])
    if first_vec is None:
        print("Correction grouping: Ollama unavailable, skipping", file=sys.stderr)
        return

    conn = sqlite3.connect(db_path, timeout=10)
    cursor = conn.cursor()
    _ensure_correction_groups_table(cursor)
    now = int(time.time())

    for idx, entry in enumerate(entries):
        if idx == 0:
            vec = first_vec
        else:
            vec = _get_embedding(entry["body"])
            if vec is None:
                continue

        match_id = _find_matching_group(cursor, vec, SIMILARITY_THRESHOLD)

        if match_id is not None:
            cursor.execute("SELECT count, correction_dates, embedding FROM correction_groups WHERE id = ?", (match_id,))
            row = cursor.fetchone()
            old_count = row[0]
            old_dates = json.loads(row[1]) if row[1] else []
            old_vec = _blob_to_embedding(row[2])

            new_count = old_count + 1
            old_dates.append(entry["date"])
            avg_vec = [(a * old_count + b) / new_count for a, b in zip(old_vec, vec)]
            cursor.execute(
                "UPDATE correction_groups SET count = ?, correction_dates = ?, embedding = ?, updated_at = ? WHERE id = ?",
                (new_count, json.dumps(old_dates), _embedding_to_blob(avg_vec), now, match_id),
            )
        else:
            cursor.execute(
                "INSERT INTO correction_groups (theme, count, correction_dates, embedding, source, status, created_at, updated_at) "
                "VALUES (?, 1, ?, ?, 'auto', 'accumulating', ?, ?)",
                (entry["header"], json.dumps([entry["date"]]), _embedding_to_blob(vec), now, now),
            )

    cursor.execute(
        "SELECT id, theme FROM correction_groups WHERE count >= ? AND status = 'accumulating'",
        (PROMOTION_THRESHOLD,),
    )
    promotable = cursor.fetchall()
    for group_id, theme in promotable:
        if _check_promoted(theme, project_root):
            cursor.execute(
                "UPDATE correction_groups SET status = 'promoted', promoted_at = ?, updated_at = ? WHERE id = ?",
                (time.strftime("%Y-%m-%d"), now, group_id),
            )
        else:
            cursor.execute(
                "UPDATE correction_groups SET status = 'pending_promotion', updated_at = ? WHERE id = ?",
                (now, group_id),
            )

    conn.commit()
    conn.close()


def main():
    if len(sys.argv) < 3:
        print("Usage: signal_processor.py <transcript_path> <epics_db_path> [session_id]", file=sys.stderr)
        sys.exit(1)

    transcript_path = sys.argv[1]
    db_path = sys.argv[2]
    session_id = sys.argv[3] if len(sys.argv) > 3 else ""

    if not os.path.isfile(transcript_path) or not os.path.isfile(db_path):
        sys.exit(0)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='decision_preferences'"
        )
        if not cursor.fetchone():
            conn.close()
            sys.exit(0)
    except Exception:
        sys.exit(0)

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
        sys.exit(0)

    if not decisions:
        conn.close()
        sys.exit(0)

    turns = parse_transcript_turns(transcript_path)
    if not turns:
        conn.close()
        sys.exit(0)

    find_decision_mention_turns(decisions, turns)

    corrections = extract_corrections(turns)

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

    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(db_path)))
        _process_correction_groups(db_path, project_root)
    except Exception as e:
        print(f"Correction grouping failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
