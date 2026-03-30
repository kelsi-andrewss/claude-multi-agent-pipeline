#!/usr/bin/env python3
"""Session agenda + correction patterns for session start context.

Usage: python3 -m hooks.lib.session_agenda <db_path> <project_root>
       python3 -m hooks.lib.session_agenda --corrections <db_path>
"""
import sqlite3, subprocess, sys, time
from datetime import datetime, timezone

STALE_SECONDS = 86400
RECENTLY_COMPLETED_HOURS = 48
RUNNING_STATES = "('in-progress','in-review','approved','running','testing','reviewing','merging')"


def query_db(db_path, sql, params=()):
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def branch_age_hours(project_root, branch, now):
    try:
        r = subprocess.run(
            ["git", "-C", project_root, "log", "-1", "--format=%ct", branch],
            capture_output=True, text=True, timeout=5,
        )
        ts = r.stdout.strip()
        if ts:
            return (now - float(ts)) / 3600
    except Exception:
        pass
    return None


def print_agenda(db_path, project_root):
    now = time.time()

    in_progress_rows = query_db(
        db_path,
        f"SELECT id, title, state, branch FROM stories "
        f"WHERE state IN {RUNNING_STATES} AND archived=0 ORDER BY id;",
    )
    stale = []
    active_in_progress = []
    for row in in_progress_rows:
        if len(row) < 4:
            continue
        sid, title, state, branch = row[0], row[1], row[2], row[3]
        hours = branch_age_hours(project_root, branch, now) if branch else None
        age_str = f"{int(hours)}h ago" if hours is not None else "unknown age"
        entry = {
            "id": sid, "title": title, "state": state,
            "branch": branch or "(no branch)", "age": age_str, "hours": hours,
        }
        if hours is not None and hours >= (STALE_SECONDS / 3600):
            stale.append(entry)
        else:
            active_in_progress.append(entry)

    ready_rows = query_db(
        db_path,
        "SELECT id, title FROM stories WHERE state='ready' AND archived=0 ORDER BY id;",
    )
    ready_stories = [{"id": r[0], "title": r[1]} for r in ready_rows if len(r) >= 2]

    cutoff_iso = datetime.fromtimestamp(
        now - RECENTLY_COMPLETED_HOURS * 3600, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")
    completed_rows = query_db(
        db_path,
        f"SELECT id, title FROM stories "
        f"WHERE state IN ('done','shipped') AND archived=0 "
        f"AND completed_at >= '{cutoff_iso}' ORDER BY completed_at DESC LIMIT 5;",
    )

    has_content = stale or active_in_progress or ready_stories or completed_rows

    if stale:
        print("")
        print("=== STALE STORIES DETECTED ===")
        for s in stale:
            print(f"  [{s['id']}] {s['title']} (stale: {s['age']})")
        print("  Run /recover to resume or discard these stories.")

    if has_content:
        print("")
        print("=== SESSION AGENDA ===")
        if active_in_progress:
            print("  In progress:")
            for s in active_in_progress:
                print(f"    [{s['id']}] {s['title']}")
        if ready_stories:
            print("  Ready to run:")
            for s in ready_stories:
                print(f"    [{s['id']}] {s['title']}")
        if completed_rows:
            print("  Recently completed:")
            for row in completed_rows:
                if len(row) >= 2:
                    print(f"    [{row[0]}] {row[1]}")
        print("")


def print_correction_patterns(db_path):
    tables = query_db(
        db_path,
        "SELECT name FROM sqlite_master WHERE type='table' AND name='correction_groups';",
    )
    if not tables:
        return

    rows = query_db(
        db_path,
        "SELECT theme, status, count, correction_dates, promoted_at "
        "FROM correction_groups "
        "WHERE status != 'dismissed' "
        "ORDER BY CASE status "
        "WHEN 'pending_promotion' THEN 0 "
        "WHEN 'accumulating' THEN 1 "
        "WHEN 'promoted' THEN 2 END, count DESC;",
    )
    if not rows:
        return

    pending = [r for r in rows if r[1] == "pending_promotion"]
    accumulating = [r for r in rows if r[1] == "accumulating" and r[2] >= 3][:15]
    promoted = [r for r in rows if r[1] == "promoted"]

    if not pending and not accumulating:
        return

    print("")
    print("=== CORRECTION PATTERNS (triaged) ===")
    if pending:
        print("  Pending promotion:")
        for r in pending:
            theme, status, count, dates = r[0], r[1], r[2], r[3]
            promoted_at = r[4] if len(r) > 4 else ""
            print(f'    [{count}x] "{theme}" (evidence: {dates})')
        print("  Process pending promotions: use /prefs to review and promote")
    if accumulating:
        print("  Accumulating:")
        for r in accumulating:
            theme, status, count, dates = r[0], r[1], r[2], r[3]
            needed = max(1, 5 - int(count))
            print(f'    [{count}x] "{theme}" (need {needed} more)')
    if promoted and (pending or accumulating):
        print("  Already promoted:")
        for r in promoted:
            theme, status, count, dates = r[0], r[1], r[2], r[3]
            promoted_at = r[4] if len(r) > 4 else ""
            print(f'    [{count}x] "{theme}" (promoted {promoted_at})')
    print("=== END CORRECTION PATTERNS ===")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--corrections":
        db_path = sys.argv[2]
        print_correction_patterns(db_path)
    else:
        db_path = sys.argv[1]
        project_root = sys.argv[2]
        print_agenda(db_path, project_root)


if __name__ == "__main__":
    main()
