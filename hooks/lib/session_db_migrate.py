#!/usr/bin/env python3
"""Schema migration + version tracking for epics.db.

Usage: python3 -m hooks.lib.session_db_migrate <db_path>

F-020: Tracks schema_version to skip already-applied migrations.
"""
import json, sqlite3, sys

CURRENT_VERSION = 7


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
    if version < 2:
        _migrate_v2(conn)
    if version < 7:
        _migrate_v7(conn)

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


def _migrate_v2(conn):
    """Reset raw-text promoted entries for re-distillation.

    Entries below RULE_THRESHOLD (5) are demoted to pending_promotion.
    Entries at threshold+ with non-RULE text are reset for re-distillation
    by stop_processor Stage 4.
    """
    # Demote sub-threshold entries that were promoted with raw text
    conn.execute(
        "UPDATE correction_groups SET status='pending_promotion', text='' "
        "WHERE status='promoted' AND count < 5"
    )
    # Reset text for threshold+ entries that have raw text (not yet distilled)
    conn.execute(
        "UPDATE correction_groups SET status='pending_promotion' "
        "WHERE status='promoted' AND (text NOT LIKE 'RULE:%' OR text = '')"
    )


def _fix_correction_counts(conn):
    """Recompute count: max(stored_count, len(dates)).

    Older code sometimes incremented count without appending to dates array,
    so stored_count can exceed len(dates). Never decrease count — only increase
    to match dates if dates has more entries.
    """
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
            actual = max(stored_count, len(dates))
            if actual != stored_count:
                fixes.append((actual, rowid))
        if fixes:
            conn.executemany(
                "UPDATE correction_groups SET count=? WHERE rowid=?", fixes
            )
    except Exception:
        pass


def _recover_counts_from_text(conn):
    """Recover counts from text column where stored count was corrupted.

    Text patterns like "User corrected 51x on:" and "(from 21 corrections,"
    preserve the pre-corruption count values.
    """
    import re
    rows = conn.execute(
        "SELECT rowid, count, text FROM correction_groups WHERE text != '' AND text IS NOT NULL"
    ).fetchall()
    fixes = []
    for rowid, stored_count, text in rows:
        text_count = 0
        m = re.search(r'User corrected (\d+)x on:', text)
        if m:
            text_count = int(m.group(1))
        else:
            m = re.search(r'\(from (\d+) corrections', text)
            if m:
                text_count = int(m.group(1))
        if text_count > stored_count:
            fixes.append((text_count, rowid))
    if fixes:
        conn.executemany(
            "UPDATE correction_groups SET count=? WHERE rowid=?", fixes
        )


def _migrate_v7(conn):
    """Recompute counts, cluster related corrections, clean up promoted entries.

    Fixes historical data corruption from _fix_correction_counts using len(set(dates))
    instead of len(dates), and consolidates fragmented entries via semantic clustering.
    """
    import sys, os

    # Step 0: Recover counts from text column (preserves pre-corruption values)
    _recover_counts_from_text(conn)

    # Step 1: Recompute counts — max(stored, len(dates)), never decrease
    _fix_correction_counts(conn)

    # Step 2: Demote promoted entries with raw text for re-distillation
    conn.execute(
        "UPDATE correction_groups SET status='pending_promotion', text='' "
        "WHERE status='promoted' AND (text NOT LIKE 'RULE:%' OR text = '')"
    )
    conn.execute(
        "UPDATE correction_groups SET status='pending_promotion', text='' "
        "WHERE status='promoted' AND (text LIKE 'User corrected%' OR text LIKE 'Pattern (%')"
    )

    # Step 3: Semantic clustering — merge related entries
    try:
        project_root = os.path.expanduser("~/.claude")
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from hooks.lib.signal_processor import cluster_and_merge_corrections
        cursor = conn.cursor()
        absorbed = cluster_and_merge_corrections(cursor)
        if absorbed > 0:
            print(f"v7 migration: clustering merged {absorbed} entries", file=sys.stderr)
    except Exception as e:
        print(f"v7 migration: clustering skipped (Ollama may be down): {e}", file=sys.stderr)

    # Step 4: Recompute counts again after merges
    _fix_correction_counts(conn)

    # Step 5: Re-check promotion qualification for all non-dismissed entries
    rows = conn.execute(
        "SELECT id, count, correction_dates, theme, status FROM correction_groups "
        "WHERE status IN ('accumulating', 'pending_promotion')"
    ).fetchall()
    for rid, count, dates_json, theme, status in rows:
        try:
            dates = json.loads(dates_json) if dates_json else []
        except (json.JSONDecodeError, TypeError):
            dates = []
        distinct_dates = len(set(dates))
        # High-count entries qualify even with poor date tracking (historical data)
        qualifies = (count >= 5 and len(theme) >= 20) or \
                    (count >= 3 and len(theme) >= 20 and distinct_dates >= 2)
        if qualifies and status == 'accumulating':
            conn.execute(
                "UPDATE correction_groups SET status='pending_promotion' WHERE id=?",
                (rid,),
            )
        elif not qualifies and status == 'pending_promotion':
            conn.execute(
                "UPDATE correction_groups SET status='accumulating' WHERE id=?",
                (rid,),
            )


def main():
    db_path = sys.argv[1]
    migrate(db_path)


if __name__ == "__main__":
    main()
