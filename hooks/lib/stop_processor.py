#!/usr/bin/env python3
"""Background Stop hook processor.

Runs as a detached process (nohup + disown) spawned by session-learning-check.sh.
Handles all slow post-session work: correction detection, signal processing,
session summary, auto-distillation, and compliance hook generation.

Usage:
    stop_processor.py --transcript <path> --db <path> --session <id> --project <path> --cwd <path>
"""
import argparse, fcntl, json, os, signal, sqlite3, sys, time


LOCKFILE_TEMPLATE = "/tmp/stop-processor-{session}.lock"

_lock_fd = None


def _lockfile_path(session_id):
    safe = "".join(c for c in session_id if c.isalnum())
    return LOCKFILE_TEMPLATE.format(session=safe)


def _acquire_lock(session_id):
    """Acquire advisory lock via fcntl.flock(). Non-blocking.

    Opens /tmp/stop-processor-{session}.lock and attempts LOCK_EX | LOCK_NB.
    Returns True if lock acquired, False if another process holds it.
    File descriptor stored in module-level _lock_fd for process-lifetime hold.
    Lock auto-releases on process exit/crash (kernel-managed).
    """
    global _lock_fd
    path = _lockfile_path(session_id)
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd = fd
        os.write(fd, str(os.getpid()).encode())
        return True
    except (BlockingIOError, OSError):
        return False


def _release_lock(session_id):
    """Release advisory lock and close file descriptor.

    Called via atexit. Safe to call multiple times (checks _lock_fd is not None).
    """
    global _lock_fd
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            os.close(_lock_fd)
        except OSError:
            pass
        _lock_fd = None


def _connect_db(db_path):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ollama_health_check():
    """Lightweight check: attempt a test embedding. Returns True if Ollama is available."""
    try:
        from hooks.lib.embedding_utils import get_embedding
        result = get_embedding("test")
        return result is not None
    except Exception:
        return False


# -- Stage 1: Correction detection + DB upsert --

def stage_correction_detection(transcript_path, db_file, session_id, project_root):
    print("Stage 1: Correction detection", file=sys.stderr)
    from hooks.lib.signal_processor import process_session_corrections
    corrections = process_session_corrections(transcript_path, db_file, session_id, project_root)
    print(f"Stage 1 complete: {len(corrections)} corrections detected", file=sys.stderr)
    return corrections


# -- Stage 2: Signal processing (decision_preferences correlation) --

def stage_signal_processing(transcript_path, db_file, session_id, corrections=None):
    print("Stage 2: Signal processing", file=sys.stderr)
    from hooks.lib.signal_processor import main_logic
    main_logic(transcript_path, db_file, session_id, corrections=corrections)
    print("Stage 2 complete", file=sys.stderr)


# -- Stage 3: Session summary --

def stage_session_summary(transcript_path, project_root):
    print("Stage 3: Session summary", file=sys.stderr)
    from datetime import datetime

    lines = []
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except (OSError, IOError):
        print("Stage 3: skipped (cannot read transcript)", file=sys.stderr)
        return

    user_turns = sum(1 for e in lines if e.get("type") == "user")
    if user_turns < 3:
        print(f"Stage 3: skipped ({user_turns} user turns, need >= 3)", file=sys.stderr)
        return

    timestamps = []
    for entry in lines:
        ts = entry.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                timestamps.append(dt.timestamp())
            except (ValueError, TypeError):
                continue

    duration_min = int((max(timestamps) - min(timestamps)) / 60) if len(timestamps) >= 2 else 0
    if duration_min < 5:
        print(f"Stage 3: skipped ({duration_min}min duration, need >= 5)", file=sys.stderr)
        return

    edited_files = set()
    for entry in lines:
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in ("Edit", "Write"):
                fp = block.get("input", {}).get("file_path", "")
                if fp:
                    edited_files.add(os.path.basename(fp))

    topic = ", ".join(sorted(edited_files)[:5]) if edited_files else "discussion"
    today = datetime.now().strftime("%Y-%m-%d")

    sys.path.insert(0, project_root)
    from hooks.lib.om_write import om_write
    om_write(
        content=f"Session {today}: {duration_min}min, {user_turns} turns. Topic: {topic}.",
        tags=["session-summary"],
        user_id="proj:dotclaude",
    )
    print(f"Stage 3 complete: {duration_min}min, {user_turns} turns, topic: {topic}", file=sys.stderr)


# -- Stage 4: Auto-distillation --

def stage_auto_distillation(db_file, project_root):
    print("Stage 4: Auto-distillation", file=sys.stderr)
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")

    conn = _connect_db(db_file)
    rows = conn.execute(
        "SELECT theme, count, correction_dates, text FROM correction_groups WHERE status='pending_promotion'"
    ).fetchall()

    if not rows:
        conn.close()
        print("Stage 4: skipped (no pending_promotion entries)", file=sys.stderr)
        return

    sys.path.insert(0, project_root)
    from hooks.lib.om_write import om_write
    from hooks.lib.signal_processor import generate_rule, RULE_THRESHOLD

    promoted = 0
    for theme, count, dates, existing_text in rows:
        # Parse last correction date from dates array
        last_date = today
        try:
            date_list = json.loads(dates) if dates else []
            if date_list:
                last_date = date_list[-1]
        except (json.JSONDecodeError, TypeError):
            pass

        if count >= RULE_THRESHOLD:
            # Use existing rule text if signal_processor already generated it
            if existing_text and existing_text.startswith("RULE:"):
                # Strip any "(Auto-generated from N corrections)" suffix to avoid duplication
                import re as _re
                rule_core = _re.sub(r'\s*\(Auto-generated from \d+ corrections\)\s*$', '', existing_text)
                pref_text = f"{rule_core} (from {count} corrections, last: {last_date})"
            else:
                rule = generate_rule(theme)
                pref_text = f"RULE: {rule} (from {count} corrections, last: {last_date})"
        else:
            pref_text = f"Pattern ({count}/5): {theme[:200]} — will become rule at 5 corrections"

        try:
            conn.execute(
                "UPDATE correction_groups SET status='promoted', text=?, promoted_at=? WHERE theme=?",
                (pref_text, today, theme),
            )
            conn.commit()
            promoted += 1
        except Exception as e:
            print(f"Stage 4: promotion failed for {theme[:80]}: {e}", file=sys.stderr)

        try:
            om_write(content=pref_text, tags=["behavioral-pref"], user_id="proj:dotclaude")
        except Exception as e:
            print(f"Stage 4: om_write failed for {theme[:80]}: {e}", file=sys.stderr)

    conn.close()
    print(f"Stage 4 complete: {promoted} entries promoted", file=sys.stderr)


# -- Stage 5: Hook generation --

def stage_hook_generation(db_file, project_root):
    if os.environ.get("CLAUDE_AGENT_ID"):
        print("Stage 5: skipped (subagent session)", file=sys.stderr)
        return

    print("Stage 5: Hook generation", file=sys.stderr)

    conn = _connect_db(db_file)

    # Ensure dismissed status is supported (migration from older schema)
    schema_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='correction_groups'"
    ).fetchone()
    if schema_sql and "'dismissed'" not in schema_sql[0]:
        conn.executescript("""
            ALTER TABLE correction_groups RENAME TO correction_groups_old;
            CREATE TABLE correction_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                theme TEXT NOT NULL,
                status TEXT DEFAULT 'accumulating' CHECK(status IN ('accumulating','pending_promotion','promoted','dismissed')),
                count INTEGER DEFAULT 1,
                correction_dates TEXT DEFAULT '[]',
                embedding BLOB,
                promoted_at TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                source TEXT DEFAULT 'auto',
                text TEXT DEFAULT ''
            );
            INSERT INTO correction_groups SELECT * FROM correction_groups_old;
            DROP TABLE correction_groups_old;
            CREATE INDEX IF NOT EXISTS idx_correction_groups_status ON correction_groups(status);
        """)

    rows = conn.execute(
        "SELECT theme FROM correction_groups WHERE status='promoted' AND date(promoted_at) = date('now', 'localtime')"
    ).fetchall()
    conn.close()

    if not rows:
        print("Stage 5: skipped (no newly promoted entries today)", file=sys.stderr)
        return

    # Ensure compliance directory exists before generating hooks
    os.makedirs(os.path.join(project_root, 'hooks', 'compliance'), exist_ok=True)

    sys.path.insert(0, project_root)
    from hooks.lib.hook_generator import generate_hook

    generated = 0
    for (theme,) in rows:
        try:
            result = generate_hook(theme, project_root=project_root, db_file=db_file)
            if result is None:
                print(f"Hook eval: not hookable: {theme[:80]}", file=sys.stderr)
            elif result.get("skipped"):
                pass
            else:
                print(f"Hook generated: {result['path']}", file=sys.stderr)
                generated += 1
        except Exception as e:
            print(f"Hook generation failed for {theme[:80]}: {e}", file=sys.stderr)

    print(f"Stage 5 complete: {generated} hooks generated", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Background Stop hook processor")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--session", default="")
    parser.add_argument("--project", required=True)
    parser.add_argument("--cwd", default="")
    args = parser.parse_args()

    # Ensure project root is on sys.path for imports
    if args.project not in sys.path:
        sys.path.insert(0, args.project)

    # Acquire lockfile
    if not _acquire_lock(args.session):
        sys.exit(0)

    # Release lock on exit (normal or exception)
    def cleanup(*_):
        _release_lock(args.session)
    import atexit
    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    print(f"stop_processor started (PID {os.getpid()}, session {args.session})", file=sys.stderr)

    # Ollama health check
    ollama_ok = _ollama_health_check()
    if not ollama_ok:
        print("WARNING: Ollama unavailable. Correction detection and session summaries will be degraded.", file=sys.stderr)

    # Stage 1: Correction detection
    corrections = []
    try:
        corrections = stage_correction_detection(args.transcript, args.db, args.session, args.project)
    except Exception as e:
        print(f"Stage 1 FAILED: {e}", file=sys.stderr)

    # Stage 2: Signal processing (receives corrections from stage 1)
    try:
        stage_signal_processing(args.transcript, args.db, args.session, corrections=corrections)
    except Exception as e:
        print(f"Stage 2 FAILED: {e}", file=sys.stderr)

    # Stage 3: Session summary
    try:
        stage_session_summary(args.transcript, args.project)
    except Exception as e:
        print(f"Stage 3 FAILED: {e}", file=sys.stderr)

    # Stage 4: Auto-distillation
    try:
        stage_auto_distillation(args.db, args.project)
    except Exception as e:
        print(f"Stage 4 FAILED: {e}", file=sys.stderr)

    # Stage 5: Hook generation
    try:
        stage_hook_generation(args.db, args.project)
    except Exception as e:
        print(f"Stage 5 FAILED: {e}", file=sys.stderr)

    print("stop_processor complete", file=sys.stderr)


if __name__ == "__main__":
    main()
