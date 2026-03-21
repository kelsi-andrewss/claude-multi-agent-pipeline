#!/usr/bin/env python3
"""Schema migration + version tracking for epics.db.

Usage: python3 -m hooks.lib.session_db_migrate <db_path>

F-020: Tracks schema_version to skip already-applied migrations.
"""
import json, sqlite3, sys

CURRENT_VERSION = 1


def get_schema_version(conn):
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0


def migrate(db_path):
    conn = sqlite3.connect(db_path, timeout=5)
    version = get_schema_version(conn)
    if version >= CURRENT_VERSION:
        conn.close()
        return

    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now')))"
    )

    if version < 1:
        _migrate_v1(conn)

    conn.execute(
        "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
        (CURRENT_VERSION,),
    )
    conn.commit()
    conn.close()


def _migrate_v1(conn):
    for col, default in [("text", "''"), ("source", "'auto'")]:
        try:
            conn.execute(
                f"ALTER TABLE correction_groups ADD COLUMN {col} TEXT DEFAULT {default}"
            )
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_correction_groups_status "
        "ON correction_groups(status)"
    )
    conn.execute(
        "UPDATE correction_groups "
        "SET text = 'User corrected ' || count || 'x on: ' || substr(theme, 1, 200) "
        "WHERE status = 'promoted' AND (text IS NULL OR text = '')"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decision_preferences (
            id TEXT PRIMARY KEY,
            decision_type TEXT NOT NULL,
            context TEXT NOT NULL,
            chosen_path TEXT NOT NULL,
            alternatives TEXT,
            session_id TEXT,
            confidence REAL DEFAULT 0.5,
            signal_score REAL DEFAULT 0,
            signal_count INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dp_type ON decision_preferences(decision_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dp_created ON decision_preferences(created_at)"
    )
    _fix_correction_counts(conn)


def _fix_correction_counts(conn):
    try:
        rows = conn.execute(
            "SELECT rowid, correction_dates, count FROM correction_groups"
        ).fetchall()
        fixes = []
        for rowid, dates_json, stored_count in rows:
            try:
                dates = json.loads(dates_json) if dates_json else []
            except (json.JSONDecodeError, TypeError):
                continue
            actual = len(set(dates))
            if actual != stored_count:
                fixes.append((actual, rowid))
        if fixes:
            conn.executemany(
                "UPDATE correction_groups SET count=? WHERE rowid=?", fixes
            )
    except Exception:
        pass


def main():
    db_path = sys.argv[1]
    migrate(db_path)


if __name__ == "__main__":
    main()
