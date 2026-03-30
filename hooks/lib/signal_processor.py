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
    r'^<skill-|'
    r'^\[Request interrupted',
    re.IGNORECASE
)

POSITIVE_INTENT = re.compile(
    r"^(let'?s |looks good|ship it|continue|approved|woo+|yes[,.\s!]|yeah|okay|lgtm|"
    r"go ahead|do it|hell yeah|let'?s go|nice|perfect|awesome|sounds good|love it|great|cool)",
    re.IGNORECASE
)

NON_CORRECTION = re.compile(
    r"^(logged in|done|ready|fixed|deployed|"
    r"continue|go on|keep going|"
    r"always|never|sure|ok|right|correct|"
    r"you do it|no you do it|"
    r"sorry continue|that's how we fix it\??)[.!?\s]*$",
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
    embedding_calls = 0

    for i, turn in enumerate(turns):

        if turn["role"] != "user":
            prev_assistant_had_tool_use = turn.get("has_tool_use", False)
            continue

        msg = turn["content"]
        if SYSTEM_MSG.search(msg):
            continue
        if POSITIVE_INTENT.match(msg):
            continue
        if is_structural_content(msg):
            continue
        if len(msg) < 15:
            continue
        if NON_CORRECTION.match(msg):
            continue

        if embedding_calls < MAX_EMBEDDING_CALLS_PER_PHASE:
            embedding_calls += 1
            matched = is_correction(msg, prototype_embs)
        else:
            matched = None

        if matched is not None:
            theme_key = msg[:30].lower().strip()
            weight = 1.0

            if theme_key in seen_themes:
                weight = 3.0
            seen_themes[theme_key] = True

            corrections.append({
                "turn_idx": turn["turn_idx"],
                "content": msg[:300],
                "weight": weight,
                "embedding": matched,
            })

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
RULE_THRESHOLD = 5

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

# Messages that share imperative tone with corrections but aren't corrections.
# Used as a negative signal: if a message is closer to these than to CORRECTION_PROTOTYPES,
# it's an instruction/status/bug-report, not a correction.
NON_CORRECTION_PROTOTYPES = [
    "I just logged in successfully",
    "sorry, please continue where you left off",
    "yes always do that from now on",
    "no, you handle it instead of me",
    "is that how we fix this problem?",
    "kill the server and restart it from the worktree",
    "now ship the other feature too",
    "run them all through the pipeline now",
    "after the process dies it never restarts, fix the bug",
    "what exactly will you write? show me an example first",
]

PROTOTYPE_THRESHOLD = 0.65
NON_CORRECTION_MARGIN = 0.02  # Positive must beat negative by this margin
MAX_EMBEDDING_CALLS_PER_PHASE = 5  # Applied independently in extraction and grouping phases
_prototype_embeddings = None
_non_correction_embeddings = None


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


def _get_non_correction_embeddings():
    """Lazy-load and cache negative prototype embeddings. Returns None if Ollama unavailable."""
    global _non_correction_embeddings
    if _non_correction_embeddings is not None:
        return _non_correction_embeddings
    embeddings = []
    for proto in NON_CORRECTION_PROTOTYPES:
        vec = get_embedding(proto)
        if vec is None:
            return None
        embeddings.append(vec)
    _non_correction_embeddings = embeddings
    return _non_correction_embeddings


def is_correction(msg, prototype_embeddings):
    """Returns the embedding vector if msg is semantically similar to a correction prototype, else None.

    Computes cosine similarity against both positive (correction) and negative
    (non-correction) prototypes. Returns msg embedding only if:
    1. Max positive similarity >= PROTOTYPE_THRESHOLD
    2. Max positive similarity > max negative similarity + NON_CORRECTION_MARGIN
    """
    msg_vec = get_embedding(msg)
    if msg_vec is None:
        return None
    pos_similarities = [cosine_similarity(msg_vec, proto_vec) for proto_vec in prototype_embeddings]
    max_pos = max(pos_similarities)
    if max_pos < PROTOTYPE_THRESHOLD:
        return None

    neg_embeddings = _get_non_correction_embeddings()
    if neg_embeddings:
        neg_similarities = [cosine_similarity(msg_vec, neg_vec) for neg_vec in neg_embeddings]
        max_neg = max(neg_similarities)
        if max_pos < max_neg + NON_CORRECTION_MARGIN:
            return None

    return msg_vec


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


CLUSTER_THRESHOLD = 0.80


def cluster_and_merge_corrections(cursor, threshold=CLUSTER_THRESHOLD):
    """Cluster correction_groups by semantic similarity and merge related entries.

    Uses union-find at the given threshold to group entries that express the same
    behavioral correction in different words. Merges multi-member clusters into
    a single representative (highest count), dismissing the rest.

    Returns number of entries absorbed (dismissed via merge).
    """
    rows = cursor.execute(
        "SELECT id, embedding, count, correction_dates, theme, status "
        "FROM correction_groups "
        "WHERE status != 'dismissed' AND embedding IS NOT NULL"
    ).fetchall()

    if len(rows) < 2:
        return 0

    entries = []
    for row in rows:
        rid, emb_blob, count, dates_json, theme, status = row
        try:
            vec = blob_to_embedding(emb_blob)
        except Exception:
            continue
        try:
            dates = json.loads(dates_json) if dates_json else []
        except (json.JSONDecodeError, TypeError):
            dates = []
        entries.append({
            'id': rid, 'vec': vec, 'count': count,
            'dates': dates, 'theme': theme, 'status': status,
        })

    if len(entries) < 2:
        return 0

    # Union-find
    parent = {e['id']: e['id'] for e in entries}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            sim = cosine_similarity(entries[i]['vec'], entries[j]['vec'])
            if sim >= threshold:
                union(entries[i]['id'], entries[j]['id'])

    # Group by cluster root
    clusters = {}
    for e in entries:
        root = find(e['id'])
        clusters.setdefault(root, []).append(e)

    # Merge clusters with 2+ members
    absorbed = 0
    now = int(time.time())
    for members in clusters.values():
        if len(members) < 2:
            continue

        # Representative: highest count, then lowest id (oldest) as tiebreak
        members.sort(key=lambda m: (-m['count'], m['id']))
        rep = members[0]
        rest = members[1:]

        # Pick best theme for rule generation: longest non-trivial theme
        best_theme = rep['theme']
        for m in members:
            cleaned = re.sub(r'^(bro|omg|omfg|wtf|bruh|dude|yo)\b[,!?\s]*', '', m['theme'], flags=re.IGNORECASE).strip()
            cleaned_rep = re.sub(r'^(bro|omg|omfg|wtf|bruh|dude|yo)\b[,!?\s]*', '', best_theme, flags=re.IGNORECASE).strip()
            if len(cleaned) > len(cleaned_rep):
                best_theme = m['theme']

        # Combine dates and recompute count
        all_dates = list(rep['dates'])
        for m in rest:
            all_dates.extend(m['dates'])
        total_count = len(all_dates)

        # Update representative
        cursor.execute(
            "UPDATE correction_groups SET count=?, correction_dates=?, theme=?, "
            "text='', updated_at=? WHERE id=?",
            (total_count, json.dumps(all_dates), best_theme[:300], now, rep['id']),
        )

        # Re-check promotion status for representative
        distinct_dates = len(set(all_dates))
        if total_count >= PROMOTION_THRESHOLD and len(best_theme) >= 20 and distinct_dates >= 2:
            new_status = 'pending_promotion'
            cursor.execute(
                "UPDATE correction_groups SET status=? WHERE id=? AND status='accumulating'",
                (new_status, rep['id']),
            )

        # Dismiss absorbed entries
        for m in rest:
            cursor.execute(
                "UPDATE correction_groups SET status='dismissed', "
                "text=? WHERE id=?",
                (f"merged into id={rep['id']}", m['id']),
            )
            absorbed += 1

    return absorbed


def _call_gemini_sync(prompt, timeout=30):
    """Synchronous gemini CLI call. Returns response text or None on failure.

    Uses -p flag for headless mode (no interactive terminal) and pipes prompt
    via stdin to avoid shell argument length limits.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["gemini", "-p", "", "-o", "json"],
            input=prompt, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            print(f"gemini CLI exit {result.returncode}: {result.stderr[:200]}", file=sys.stderr)
            return None
        data = json.loads(result.stdout)
        return data.get("response", "")
    except subprocess.TimeoutExpired:
        print(f"gemini CLI timed out after {timeout}s", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print(f"gemini CLI returned invalid JSON: {result.stdout[:200]}", file=sys.stderr)
        return None
    except (FileNotFoundError, OSError) as e:
        print(f"gemini CLI not available: {e}", file=sys.stderr)
        return None


LLM_CLUSTER_MIN_ENTRIES = 4  # Don't bother LLM with fewer entries


def llm_cluster_corrections(cursor):
    """Use Gemini to cluster corrections by behavioral intent.

    Embedding similarity can't bridge vocabulary gaps ("bro use the skill" vs
    "why didn't you use ship"). This function sends all non-dismissed themes
    to Gemini and asks it to group them by underlying behavioral correction.

    Returns number of entries absorbed (dismissed via merge).
    """
    # Quick health check — bail fast if Gemini is down rather than waiting 90s
    health = _call_gemini_sync('Return: {"ok":true}', timeout=15)
    if health is None:
        print("llm_cluster: Gemini unavailable, skipping", file=sys.stderr)
        return 0

    # Only cluster entries with count >= 2 — singletons don't benefit from LLM grouping
    # and sending 100+ entries makes the prompt too large / slow
    rows = cursor.execute(
        "SELECT id, count, correction_dates, theme, status "
        "FROM correction_groups "
        "WHERE status IN ('accumulating', 'pending_promotion') AND count >= 2"
    ).fetchall()

    if len(rows) < LLM_CLUSTER_MIN_ENTRIES:
        return 0

    # Build ID→entry map
    entries_by_id = {}
    theme_list = []
    for rid, count, dates_json, theme, status in rows:
        try:
            dates = json.loads(dates_json) if dates_json else []
        except (json.JSONDecodeError, TypeError):
            dates = []
        entries_by_id[rid] = {
            'id': rid, 'count': count, 'dates': dates,
            'theme': theme, 'status': status,
        }
        theme_list.append(f"  id={rid}: {theme[:200]}")

    prompt = (
        "[System: You are a clustering engine. You group user correction messages by "
        "the behavioral intent they express. Two messages belong in the same cluster "
        "if they are telling the AI to change the same behavior, even if they use "
        "completely different words or levels of profanity.]\n\n"
        "Below are correction messages from a user to an AI assistant. "
        "Group them into clusters where each cluster represents ONE behavioral correction. "
        "Only group entries that clearly express the SAME underlying complaint.\n\n"
        "Messages:\n" + "\n".join(theme_list) + "\n\n"
        "Return ONLY valid JSON — no markdown, no code blocks. Format:\n"
        '[{"cluster_name": "short-label", "ids": [1, 2, 3]}, ...]\n\n'
        "Rules:\n"
        "- Only include clusters with 2+ members\n"
        "- Be conservative — when unsure, leave entries unclustered\n"
        "- Ignore profanity/tone differences, focus on what behavior is being corrected\n"
        "- cluster_name should be a short kebab-case label like 'use-ship-skill' or 'research-first'"
    )

    raw = _call_gemini_sync(prompt, timeout=90)
    if not raw:
        return 0

    # Parse JSON response — handle markdown wrapping
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

    try:
        clusters = json.loads(text)
    except json.JSONDecodeError:
        print(f"llm_cluster: invalid JSON response: {text[:200]}", file=sys.stderr)
        return 0

    if not isinstance(clusters, list):
        return 0

    absorbed = 0
    now = int(time.time())

    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        ids = cluster.get("ids", [])
        # Validate: all IDs must exist in our entry map
        valid_ids = [i for i in ids if i in entries_by_id]
        if len(valid_ids) < 2:
            continue

        members = [entries_by_id[i] for i in valid_ids]
        # Representative: highest count, then oldest (lowest id)
        members.sort(key=lambda m: (-m['count'], m['id']))
        rep = members[0]
        rest = members[1:]

        # Pick best theme: longest non-trivial
        best_theme = rep['theme']
        for m in members:
            cleaned = re.sub(r'^(bro|omg|omfg|wtf|bruh|dude|yo)\b[,!?\s]*', '', m['theme'], flags=re.IGNORECASE).strip()
            cleaned_rep = re.sub(r'^(bro|omg|omfg|wtf|bruh|dude|yo)\b[,!?\s]*', '', best_theme, flags=re.IGNORECASE).strip()
            if len(cleaned) > len(cleaned_rep):
                best_theme = m['theme']

        all_dates = list(rep['dates'])
        for m in rest:
            all_dates.extend(m['dates'])
        total_count = len(all_dates)

        cursor.execute(
            "UPDATE correction_groups SET count=?, correction_dates=?, theme=?, "
            "text='', updated_at=? WHERE id=?",
            (total_count, json.dumps(all_dates), best_theme[:300], now, rep['id']),
        )

        distinct_dates = len(set(all_dates))
        if total_count >= PROMOTION_THRESHOLD and len(best_theme) >= 20 and distinct_dates >= 2:
            cursor.execute(
                "UPDATE correction_groups SET status=? WHERE id=? AND status='accumulating'",
                ('pending_promotion', rep['id']),
            )

        cluster_name = cluster.get("cluster_name", "unknown")
        for m in rest:
            cursor.execute(
                "UPDATE correction_groups SET status='dismissed', "
                "text=? WHERE id=?",
                (f"llm-merged into id={rep['id']} ({cluster_name})", m['id']),
            )
            del entries_by_id[m['id']]
            absorbed += 1

    return absorbed


_EXPLETIVES = r'(?:bro|omg|omfg|wtf|bruh|dude|yo|buddy|ffs|jfc)'
_PROFANITY = r'(?:what the fuck|fuck(?:ing)?|damn|stupid\s+ass|stupid|ass|shit(?:ty)?)'


def _clean_text(text):
    """Strip dates, expletives, and profanity from correction text."""
    # Strip leading date prefixes like "2026-03-04 — "
    text = re.sub(r'^\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?\s*[—–-]\s*', '', text).strip()
    # Strip leading/trailing expletives
    text = re.sub(rf'^{_EXPLETIVES}\b[,!?\s]*', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(rf'[,!?\s]*{_EXPLETIVES}[.!?]*$', '', text, flags=re.IGNORECASE).strip()
    # Strip inline profanity
    text = re.sub(rf'\b{_PROFANITY}\b\s*', '', text, flags=re.IGNORECASE).strip()
    # Clean up double spaces and leading/trailing punctuation
    text = re.sub(r'\s{2,}', ' ', text).strip(' ,.')
    return text


def _degerund(phrase):
    """Convert leading gerund to base form: 'creating hooks' -> 'create hooks'."""
    m = re.match(r'^(\w+)ing\b(.*)$', phrase)
    if not m:
        return phrase
    stem, rest = m.group(1), m.group(2)
    # Double consonant: running→run, stopping→stop
    if len(stem) >= 2 and stem[-1] == stem[-2]:
        return stem[:-1] + rest
    # Silent-e verbs: creating→create, making→make
    if stem and stem[-1] in 'bcdfghjklmnpqrstvwxyz':
        return stem + 'e' + rest
    return stem + rest


def generate_rule(theme_text):
    """Convert a correction theme into a positive-instruction rule.

    Extracts the behavioral pattern from the correction text and reframes it
    as a directive. E.g. "don't skip research" -> "Always do research first."
    """
    text = _clean_text(theme_text)
    lower = text.lower()

    if not text or len(text) < 10:
        return f"Per repeated user correction: {theme_text.strip()}"

    # Pattern: "don't/do not/stop/never <doing X>"
    neg_match = re.match(r"(?:don'?t|do not|stop|quit|never)\s+(.+)", lower)
    if neg_match:
        action = neg_match.group(1).strip().rstrip('.')
        return f"Never {action}"

    # Pattern: "why do you keep X" -> "Never X" (degerund: creating→create)
    keep_match = re.match(r"why (?:do )?(?:you|u) keep\s+(.+)", lower)
    if keep_match:
        bad_action = _degerund(keep_match.group(1).strip().rstrip('?.'))
        return f"Never {bad_action}"

    # Pattern: "why are you X-ing" -> "Never X" (degerund)
    why_are_match = re.match(r"why are you\s+(.+)", lower)
    if why_are_match:
        bad_action = _degerund(why_are_match.group(1).strip().rstrip('?.'))
        return f"Never {bad_action}"

    # Pattern: "why didn't you X" -> "Always X"
    why_match = re.match(r"why (?:didn'?t|don'?t|aren'?t|isn'?t|won'?t) (?:you|u)\s+(.+)", lower)
    if why_match:
        expected = why_match.group(1).strip().rstrip('?.')
        return f"Always {expected}"

    # Pattern: "use X" / "run X" / "do X"
    use_match = re.match(r"(use|do|run|call|try)\s+(.+?)(?:\s+instead)?$", lower)
    if use_match:
        verb, action = use_match.group(1), use_match.group(2).strip()
        return f"Always {verb} {action}"

    # Pattern: "no. this is for X" -> "This tool/context is for X"
    this_match = re.match(r"(?:no[.!,]?\s*)?this is (?:for\s+)?(.+)", lower)
    if this_match:
        purpose = this_match.group(1).strip().rstrip('.')
        return f"This is for {purpose} — use accordingly"

    # Pattern: "X comes first" / "X before Y"
    first_match = re.search(r'(\w[\w\s]*?)\s+comes?\s+first', lower)
    if first_match:
        priority = first_match.group(1).strip()
        return f"Always do {priority} first"

    # Fallback: use the cleaned text directly
    return f"Per repeated user correction: {text}"


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

    conn = None
    try:
        conn = sqlite3.connect(db_file, timeout=10)
        cursor = conn.cursor()
        _ensure_correction_groups_table(cursor)
        now = int(time.time())

        for correction in all_corrections:
            theme_text = correction["content"]
            theme_key = theme_text[:300]

            # Per-session rate limit: skip DB increment if theme already seen this session
            if theme_key in seen_themes:
                continue
            seen_themes.add(theme_key)

            # Reuse the embedding computed during extraction
            correction_embedding = correction.get("embedding")

            # Try semantic matching via embedding before falling back to exact text match
            matched_group_id = None
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
                if row[3] == 'dismissed':
                    continue
                if row[3] == 'promoted':
                    # Reinforce: increment count and append date (rule stays promoted)
                    old_dates = json.loads(row[2]) if row[2] else []
                    old_dates.append(today)
                    new_count = row[1] + 1
                    cursor.execute(
                        "UPDATE correction_groups SET count=?, correction_dates=?, updated_at=? WHERE id=?",
                        (new_count, json.dumps(old_dates), now, row[0])
                    )
                    continue
                new_count = row[1] + 1
                old_dates = json.loads(row[2]) if row[2] else []
                old_dates.append(today)
                distinct_dates = len(set(old_dates))
                qualifies = new_count >= PROMOTION_THRESHOLD and len(theme_key) >= 20 and distinct_dates >= 2
                new_status = 'pending_promotion' if qualifies else row[3]
                updates = {
                    'count': new_count, 'correction_dates': json.dumps(old_dates),
                    'status': new_status, 'updated_at': now,
                }
                # At rule threshold, auto-generate actionable rule text
                if new_count >= RULE_THRESHOLD:
                    rule_text = generate_rule(theme_text)
                    updates['text'] = f"RULE: {rule_text} (Auto-generated from {new_count} corrections)"
                cursor.execute(
                    "UPDATE correction_groups SET count=?, correction_dates=?, status=?, updated_at=?"
                    + (", text=?" if 'text' in updates else "")
                    + " WHERE id=?",
                    tuple(updates[k] for k in ['count', 'correction_dates', 'status', 'updated_at']
                          + (['text'] if 'text' in updates else []))
                    + (row[0],)
                )
            else:
                # Don't create orphan rows without embeddings -- they can never be deduplicated
                if correction_embedding is None:
                    continue
                embedding_blob = embedding_to_blob(correction_embedding)
                cursor.execute(
                    "INSERT INTO correction_groups (theme, status, count, correction_dates, embedding, source, created_at, updated_at) "
                    "VALUES (?, 'accumulating', 1, ?, ?, 'auto', ?, ?)",
                    (theme_text[:300], json.dumps([today]), embedding_blob, now, now)
                )

        conn.commit()
    except Exception as e:
        print(f"process_session_corrections DB error: {e}", file=sys.stderr)
    finally:
        if conn is not None:
            conn.close()

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
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='merge_outcomes'"
            )
            if cursor.fetchone():
                rows = cursor.execute(
                    "SELECT model, COUNT(*) as total FROM merge_outcomes "
                    "WHERE success IS NOT NULL AND model IS NOT NULL "
                    "GROUP BY model HAVING COUNT(*) >= 5"
                ).fetchall()
                for model, total in rows:
                    rate = model_rates.get(model, 0.0)
                    if rate < 0.7:
                        print(
                            f"Warning: model '{model}' success rate {rate:.1%} "
                            f"({int(rate * total)}/{total}) below 0.7 threshold",
                            file=sys.stderr,
                        )
            conn.close()
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


def main_logic(transcript_path, db_path, session_id="", corrections=None):
    """Core signal processing: correlate corrections with decision_preferences.

    Performs:
    1. Connect to db_path, query recent decision_preferences
    2. Parse transcript turns, find decision mention turns
    3. Use provided corrections (or detect if not provided)
    4. For matched corrections: decrement signal_score by correction weight
    5. For unmatched decisions: increment signal_score by 0.5 (implicit approval)
    6. Commit and close

    Args:
        transcript_path: Path to JSONL transcript file.
        db_path: Path to epics.db.
        session_id: Session identifier for filtering decisions.
        corrections: Pre-detected corrections list from stage 1. If None,
            falls back to calling process_session_corrections (standalone usage).

    Returns:
        None. Side effects: updates decision_preferences.signal_score/signal_count
        in db_path.

    Exits silently (returns None) when:
        - transcript_path or db_path don't exist
        - decision_preferences table missing
        - No recent decisions found
        - No transcript turns parsed
    """
    if not os.path.isfile(transcript_path) or not os.path.isfile(db_path):
        return

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
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

    if corrections is None:
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
