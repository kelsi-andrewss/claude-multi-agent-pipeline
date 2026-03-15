#!/usr/bin/env python3
"""Initialize run-state.db and register a new session.

Usage: python3 init-run-db.py --session-id <uuid> --dev-branch <name>

Creates the run-state.db schema (4 tables), cleans stale sessions older
than 1 hour, and inserts a new session row. Emits JSON to stdout.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

DB_PATH = os.path.expanduser("~/.claude/.claude/run-state.db")

SCHEMA_DDL = [
    """CREATE TABLE IF NOT EXISTS run_sessions (
        id TEXT PRIMARY KEY,
        started_at INTEGER NOT NULL,
        dev_branch TEXT NOT NULL,
        status TEXT DEFAULT 'running' CHECK(status IN ('running','done','failed','interrupted')),
        completed_at INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS story_executions (
        session_id TEXT NOT NULL REFERENCES run_sessions(id),
        story_id TEXT NOT NULL,
        batch INTEGER NOT NULL,
        worktree_path TEXT,
        story_branch TEXT,
        agent_id TEXT,
        step TEXT DEFAULT 'pending' CHECK(step IN ('pending','worktree_created','launched','done','blocked','need_decision')),
        result_summary TEXT,
        started_at INTEGER,
        completed_at INTEGER,
        PRIMARY KEY (session_id, story_id)
    )""",
    """CREATE TABLE IF NOT EXISTS batch_verifications (
        session_id TEXT NOT NULL REFERENCES run_sessions(id),
        batch INTEGER NOT NULL,
        status TEXT CHECK(status IN ('pass','fail','skipped')),
        output TEXT,
        verified_at INTEGER,
        PRIMARY KEY (session_id, batch)
    )""",
    """CREATE TABLE IF NOT EXISTS merge_results (
        session_id TEXT NOT NULL REFERENCES run_sessions(id),
        story_id TEXT NOT NULL,
        diff_gate TEXT CHECK(diff_gate IN ('pass','warn','fail')),
        unexpected_files TEXT,
        test_passed INTEGER,
        error_classification TEXT,
        test_output TEXT,
        retry_count INTEGER DEFAULT 0,
        merged_at INTEGER,
        PRIMARY KEY (session_id, story_id)
    )""",
    """CREATE TABLE IF NOT EXISTS merge_queue (
        id INTEGER PRIMARY KEY,
        story_id TEXT NOT NULL,
        priority INTEGER DEFAULT 0,
        write_targets TEXT,
        status TEXT DEFAULT 'queued' CHECK(status IN ('queued','merging','merged','blocked','cancelled')),
        queued_at TEXT DEFAULT (datetime('now')),
        merged_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS merge_outcomes (
        id INTEGER PRIMARY KEY,
        story_id TEXT NOT NULL UNIQUE,
        epic_id TEXT,
        agent TEXT,
        model TEXT,
        domain_tags TEXT,
        predicted_conflict BOOLEAN,
        actual_conflict BOOLEAN,
        success BOOLEAN,
        cycle_time_s INTEGER,
        revert_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS agent_heartbeats (
        id INTEGER PRIMARY KEY,
        story_id TEXT NOT NULL,
        agent_id TEXT,
        last_tool_call TEXT,
        tool_call_hash TEXT,
        repeat_count INTEGER DEFAULT 0,
        token_estimate INTEGER DEFAULT 0,
        last_heartbeat TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE INDEX IF NOT EXISTS idx_heartbeats_story ON agent_heartbeats(story_id)""",
]


def emit(obj):
    print(json.dumps(obj))


def main():
    parser = argparse.ArgumentParser(description="Initialize run-state.db")
    parser.add_argument("--session-id", required=True, help="UUID for the new session")
    parser.add_argument("--dev-branch", required=True, help="Dev branch name")
    args = parser.parse_args()

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
    except sqlite3.Error as e:
        emit({"status": "error", "error": f"Cannot open run-state.db: {e}"})
        sys.exit(2)

    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")

    for ddl in SCHEMA_DDL:
        cursor.execute(ddl)

    now = int(time.time())
    one_hour_ago = now - 3600

    stale = cursor.execute(
        "SELECT id FROM run_sessions WHERE status='running' AND started_at < ?",
        (one_hour_ago,),
    ).fetchall()

    stale_ids = [row[0] for row in stale]
    for sid in stale_ids:
        cursor.execute("DELETE FROM story_executions WHERE session_id=?", (sid,))
        cursor.execute("DELETE FROM batch_verifications WHERE session_id=?", (sid,))
        cursor.execute("DELETE FROM merge_results WHERE session_id=?", (sid,))
        cursor.execute(
            "UPDATE run_sessions SET status='interrupted' WHERE id=?", (sid,)
        )

    cursor.execute(
        "INSERT INTO run_sessions (id, started_at, dev_branch, status) VALUES (?, ?, ?, 'running')",
        (args.session_id, now, args.dev_branch),
    )

    conn.commit()
    conn.close()

    emit({
        "status": "success",
        "session_id": args.session_id,
        "stale_cleaned": len(stale_ids),
    })


if __name__ == "__main__":
    main()
