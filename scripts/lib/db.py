"""Shared SQLite connection factory for scripts."""
import sqlite3
from pathlib import Path

DEFAULT_DB = Path.home() / ".claude" / ".claude" / "run-state.db"


def open_run_state_db(db_path=None):
    """Open run-state.db with standard pragmas."""
    path = str(db_path or DEFAULT_DB)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def open_epics_db():
    """Open epics.db with standard pragmas."""
    path = str(Path.home() / ".claude" / ".claude" / "epics.db")
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
