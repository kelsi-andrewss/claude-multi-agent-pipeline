#!/usr/bin/env python3
"""Merge queue: priority-based queue with write-target overlap detection.

Usage:
    python3 merge-queue.py enqueue --story-id <id> --write-targets <json-array> [--priority <int>]
    python3 merge-queue.py dequeue --story-id <id>
    python3 merge-queue.py next
    python3 merge-queue.py status [--story-id <id>]
    python3 merge-queue.py cancel --story-id <id>

Exit codes: 0 = success, 1 = functional error, 2 = system error.
Emits a single JSON object on stdout. Debug logging on stderr.
"""
import argparse
import json
import os
import sqlite3
import sys

DB_PATH = os.path.expanduser("~/.claude/.claude/run-state.db")


def emit(obj):
    print(json.dumps(obj))


def connect():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
    except sqlite3.Error as e:
        emit({"status": "error", "error": f"Cannot open run-state.db: {e}"})
        sys.exit(2)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    return conn, cursor


def cmd_enqueue(args):
    conn, cursor = connect()

    existing = cursor.execute(
        "SELECT status FROM merge_queue WHERE story_id=? AND status IN ('queued','merging')",
        (args.story_id,),
    ).fetchone()

    if existing:
        emit({"status": "error", "error": f"{args.story_id} is already in the queue (status: {existing['status']})"})
        conn.close()
        sys.exit(1)

    cursor.execute(
        "INSERT INTO merge_queue (story_id, priority, write_targets, status) VALUES (?, ?, ?, 'queued')",
        (args.story_id, args.priority, args.write_targets),
    )
    conn.commit()

    position = cursor.execute(
        """SELECT COUNT(*) as pos FROM merge_queue
           WHERE status IN ('queued','merging')
             AND (priority > ? OR (priority = ? AND queued_at <= (
               SELECT queued_at FROM merge_queue WHERE story_id=? AND status='queued'
               ORDER BY id DESC LIMIT 1
             )))""",
        (args.priority, args.priority, args.story_id),
    ).fetchone()["pos"]

    conn.close()
    emit({"status": "success", "action": "enqueued", "story_id": args.story_id, "queue_position": position})


def cmd_dequeue(args):
    conn, cursor = connect()

    row = cursor.execute(
        "SELECT status FROM merge_queue WHERE story_id=? AND status='merging'",
        (args.story_id,),
    ).fetchone()

    if not row:
        emit({"status": "error", "error": f"{args.story_id} is not in 'merging' status"})
        conn.close()
        sys.exit(1)

    cursor.execute(
        "UPDATE merge_queue SET status='merged', merged_at=datetime('now') WHERE story_id=? AND status='merging'",
        (args.story_id,),
    )
    conn.commit()

    updated = cursor.execute(
        "SELECT merged_at FROM merge_queue WHERE story_id=? AND status='merged' ORDER BY id DESC LIMIT 1",
        (args.story_id,),
    ).fetchone()

    conn.close()
    emit({"status": "success", "action": "dequeued", "story_id": args.story_id, "merged_at": updated["merged_at"]})


def parse_targets(raw):
    if not raw:
        return set()
    try:
        targets = json.loads(raw)
        if isinstance(targets, list):
            return set(targets)
    except (json.JSONDecodeError, TypeError):
        pass
    return set()


def cmd_next(_args):
    conn, cursor = connect()
    cursor.execute("BEGIN IMMEDIATE")

    queued_rows = cursor.execute(
        "SELECT id, story_id, priority, write_targets FROM merge_queue WHERE status='queued' ORDER BY priority DESC, queued_at ASC",
    ).fetchall()

    merging_rows = cursor.execute(
        "SELECT write_targets FROM merge_queue WHERE status='merging'",
    ).fetchall()

    merging_count = len(merging_rows)
    queued_count = len(queued_rows)

    if queued_count == 0:
        conn.commit()
        conn.close()
        emit({"status": "success", "action": "none", "reason": "queue_empty", "queued_count": 0, "merging_count": merging_count})
        return

    active_targets = set()
    for row in merging_rows:
        active_targets |= parse_targets(row["write_targets"])

    for row in queued_rows:
        story_targets = parse_targets(row["write_targets"])
        overlap = story_targets & active_targets
        if not overlap:
            cursor.execute(
                "UPDATE merge_queue SET status='merging' WHERE id=?",
                (row["id"],),
            )
            conn.commit()
            conn.close()
            targets_list = sorted(story_targets)
            emit({
                "status": "success",
                "action": "next",
                "story_id": row["story_id"],
                "write_targets": targets_list,
                "priority": row["priority"],
            })
            return

    # All queued stories conflict with active merges.
    # Force-sequential fallback: if nothing is actively merging but everything
    # is "blocked" by stale state, force the highest-priority queued story through.
    if merging_count == 0:
        forced = queued_rows[0]
        cursor.execute(
            "UPDATE merge_queue SET status='merging' WHERE id=?",
            (forced["id"],),
        )
        conn.commit()
        conn.close()
        targets_list = sorted(parse_targets(forced["write_targets"]))
        emit({
            "status": "success",
            "action": "next",
            "story_id": forced["story_id"],
            "write_targets": targets_list,
            "priority": forced["priority"],
        })
        return

    conn.commit()
    conn.close()
    emit({
        "status": "success",
        "action": "none",
        "reason": "all_blocked",
        "queued_count": queued_count,
        "merging_count": merging_count,
    })


def cmd_status(args):
    conn, cursor = connect()

    if args.story_id:
        row = cursor.execute(
            "SELECT story_id, priority, status, write_targets, queued_at, merged_at FROM merge_queue WHERE story_id=? ORDER BY id DESC LIMIT 1",
            (args.story_id,),
        ).fetchone()
        conn.close()
        if not row:
            emit({"status": "error", "error": f"{args.story_id} not found in merge queue"})
            sys.exit(1)
        emit({
            "status": "success",
            "story": {
                "story_id": row["story_id"],
                "priority": row["priority"],
                "status": row["status"],
                "write_targets": json.loads(row["write_targets"]) if row["write_targets"] else [],
                "queued_at": row["queued_at"],
                "merged_at": row["merged_at"],
            },
        })
        return

    rows = cursor.execute(
        "SELECT story_id, priority, status, write_targets, queued_at, merged_at FROM merge_queue WHERE status IN ('queued','merging') ORDER BY priority DESC, queued_at ASC",
    ).fetchall()

    counts_rows = cursor.execute(
        "SELECT status, COUNT(*) as cnt FROM merge_queue GROUP BY status",
    ).fetchall()
    conn.close()

    counts = {r["status"]: r["cnt"] for r in counts_rows}
    queue = []
    for row in rows:
        queue.append({
            "story_id": row["story_id"],
            "priority": row["priority"],
            "status": row["status"],
            "write_targets": json.loads(row["write_targets"]) if row["write_targets"] else [],
            "queued_at": row["queued_at"],
        })

    emit({
        "status": "success",
        "queue": queue,
        "counts": {
            "queued": counts.get("queued", 0),
            "merging": counts.get("merging", 0),
            "merged": counts.get("merged", 0),
            "blocked": counts.get("blocked", 0),
            "cancelled": counts.get("cancelled", 0),
        },
    })


def cmd_cancel(args):
    conn, cursor = connect()

    row = cursor.execute(
        "SELECT status FROM merge_queue WHERE story_id=? AND status IN ('queued','merging')",
        (args.story_id,),
    ).fetchone()

    if not row:
        emit({"status": "error", "error": f"{args.story_id} not found in queue with cancellable status"})
        conn.close()
        sys.exit(1)

    cursor.execute(
        "UPDATE merge_queue SET status='cancelled' WHERE story_id=? AND status IN ('queued','merging')",
        (args.story_id,),
    )
    conn.commit()
    conn.close()
    emit({"status": "success", "action": "cancelled", "story_id": args.story_id})


def main():
    parser = argparse.ArgumentParser(description="Merge queue: priority-based with write-target overlap detection")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_enqueue = subparsers.add_parser("enqueue")
    p_enqueue.add_argument("--story-id", required=True)
    p_enqueue.add_argument("--write-targets", required=True)
    p_enqueue.add_argument("--priority", type=int, default=0)

    p_dequeue = subparsers.add_parser("dequeue")
    p_dequeue.add_argument("--story-id", required=True)

    subparsers.add_parser("next")

    p_status = subparsers.add_parser("status")
    p_status.add_argument("--story-id", default=None)

    p_cancel = subparsers.add_parser("cancel")
    p_cancel.add_argument("--story-id", required=True)

    args = parser.parse_args()

    dispatch = {
        "enqueue": cmd_enqueue,
        "dequeue": cmd_dequeue,
        "next": cmd_next,
        "status": cmd_status,
        "cancel": cmd_cancel,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
