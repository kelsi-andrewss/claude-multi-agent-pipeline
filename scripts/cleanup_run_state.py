#!/usr/bin/env python3
"""Clean up a completed session in run-state.db.

Usage: python3 cleanup_run_state.py --session-id <uuid>

Marks the session as done and removes associated execution rows.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.db import open_run_state_db


def emit(obj):
    print(json.dumps(obj))


def main():
    parser = argparse.ArgumentParser(description="Clean up a session in run-state.db")
    parser.add_argument("--session-id", required=True, help="UUID of the session to clean up")
    args = parser.parse_args()

    try:
        conn = open_run_state_db()
    except sqlite3.Error as e:
        emit({"status": "error", "error": f"Cannot open run-state.db: {e}"})
        sys.exit(2)

    cursor = conn.cursor()
    cleaned_rows = 0

    now = int(time.time())
    cursor.execute(
        "UPDATE run_sessions SET status='done', completed_at=? WHERE id=? AND status='running'",
        (now, args.session_id),
    )
    cleaned_rows += cursor.rowcount

    for table in ("story_executions", "batch_verifications", "merge_results"):
        cursor.execute(f"DELETE FROM {table} WHERE session_id=?", (args.session_id,))
        cleaned_rows += cursor.rowcount

    conn.commit()
    conn.close()

    emit({
        "status": "success",
        "session_id": args.session_id,
        "cleaned_rows": cleaned_rows,
    })


if __name__ == "__main__":
    main()
