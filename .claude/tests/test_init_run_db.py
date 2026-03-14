"""Tests for init-run-db.py."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

import pytest

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "init-run-db.py")


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = str(tmp_path / "run-state.db")
    monkeypatch.setenv("HOME", str(tmp_path))
    os.makedirs(tmp_path / ".claude" / ".claude", exist_ok=True)
    actual_db = str(tmp_path / ".claude" / ".claude" / "run-state.db")
    return actual_db


def run_init(session_id, dev_branch, db_path):
    """Run init-run-db.py as a subprocess, patching DB_PATH via env."""
    env = os.environ.copy()
    parent = os.path.dirname(os.path.dirname(db_path))
    env["HOME"] = os.path.dirname(parent)
    result = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--session-id", session_id, "--dev-branch", dev_branch],
        capture_output=True, text=True, env=env,
    )
    return result


def test_creates_all_tables(tmp_path):
    os.makedirs(tmp_path / ".claude" / ".claude", exist_ok=True)
    db_path = str(tmp_path / ".claude" / ".claude" / "run-state.db")
    result = run_init("test-session-1", "dev", db_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    output = json.loads(result.stdout.strip())
    assert output["status"] == "success"
    assert output["session_id"] == "test-session-1"

    conn = sqlite3.connect(db_path)
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    conn.close()

    assert "run_sessions" in tables
    assert "story_executions" in tables
    assert "batch_verifications" in tables
    assert "merge_results" in tables


def test_stale_session_cleanup(tmp_path):
    os.makedirs(tmp_path / ".claude" / ".claude", exist_ok=True)
    db_path = str(tmp_path / ".claude" / ".claude" / "run-state.db")

    # First run to create schema
    run_init("setup-session", "dev", db_path)

    # Insert a stale session (2 hours old)
    conn = sqlite3.connect(db_path)
    two_hours_ago = int(time.time()) - 7200
    conn.execute(
        "INSERT INTO run_sessions (id, started_at, dev_branch, status) VALUES (?, ?, ?, 'running')",
        ("stale-session", two_hours_ago, "dev"),
    )
    conn.execute(
        "INSERT INTO story_executions (session_id, story_id, batch) VALUES (?, ?, ?)",
        ("stale-session", "story-1", 0),
    )
    conn.execute(
        "INSERT INTO merge_results (session_id, story_id, test_passed, retry_count) VALUES (?, ?, ?, ?)",
        ("stale-session", "story-1", 0, 0),
    )
    conn.commit()
    conn.close()

    # Second run should clean stale session
    result = run_init("new-session", "dev", db_path)
    assert result.returncode == 0
    output = json.loads(result.stdout.strip())
    assert output["stale_cleaned"] == 1

    conn = sqlite3.connect(db_path)
    status = conn.execute(
        "SELECT status FROM run_sessions WHERE id='stale-session'"
    ).fetchone()[0]
    assert status == "interrupted"

    # Child rows should be deleted
    child_count = conn.execute(
        "SELECT COUNT(*) FROM story_executions WHERE session_id='stale-session'"
    ).fetchone()[0]
    assert child_count == 0

    merge_count = conn.execute(
        "SELECT COUNT(*) FROM merge_results WHERE session_id='stale-session'"
    ).fetchone()[0]
    assert merge_count == 0

    conn.close()


def test_idempotent_schema(tmp_path):
    os.makedirs(tmp_path / ".claude" / ".claude", exist_ok=True)
    db_path = str(tmp_path / ".claude" / ".claude" / "run-state.db")

    result1 = run_init("session-a", "dev", db_path)
    assert result1.returncode == 0

    result2 = run_init("session-b", "dev", db_path)
    assert result2.returncode == 0

    conn = sqlite3.connect(db_path)
    sessions = conn.execute("SELECT id FROM run_sessions ORDER BY id").fetchall()
    conn.close()

    session_ids = [row[0] for row in sessions]
    assert "session-a" in session_ids
    assert "session-b" in session_ids
