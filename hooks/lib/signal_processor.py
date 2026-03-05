#!/usr/bin/env python3
"""Signal processor: correlate user corrections with recorded decision preferences.

Usage: signal_processor.py <transcript_path> <epics_db_path> <session_id>

Reads the session transcript, identifies corrections, matches them against
decision_preferences from the current session or last 24 hours, and updates
signal_score/signal_count accordingly.
"""
import json, os, re, sqlite3, sys, time


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
                elif isinstance(c, str):
                    content_text = c
        else:
            continue

        if content_text:
            turns.append({"role": role, "content": content_text.strip(), "turn_idx": len(turns)})

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


def is_frustration(msg):
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

    for i, turn in enumerate(turns):
        if turn["role"] != "user":
            continue

        msg = turn["content"]
        if SYSTEM_MSG.search(msg):
            continue

        matched = False

        if len(msg) < 150 and IMPERATIVE_STARTS.match(msg):
            matched = True
        if not matched and is_frustration(msg):
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

    return corrections


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


if __name__ == "__main__":
    main()
