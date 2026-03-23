#!/usr/bin/env python3
"""OpenMemory pruning + tool-learning query at session start.

Usage: python3 -m hooks.lib.session_om_query <om_db_path>
"""
import os, sys, time


DEFAULT_DECAY = 0.05


def om_query(om_db, sql, params=()):
    try:
        import sqlite3
        conn = sqlite3.connect(om_db, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def trunc(s, n=150):
    return s[:n] + "..." if len(s) > n else s


def prune_and_query(om_db):
    now = time.time()

    try:
        project_root = os.path.expanduser("~/.claude")
        sys.path.insert(0, project_root)
        from hooks.lib.om_write import prune_expired
        pruned = prune_expired()
        if pruned > 0:
            print(f"  (pruned {pruned} expired OpenMemory entries)")
    except Exception:
        pass

    decay_score = (
        f"feedback_score * EXP(-COALESCE(decay_lambda, {DEFAULT_DECAY}) "
        f"* (({int(now)} - COALESCE(last_seen_at, created_at)) / 86400.0))"
    )

    learnings = om_query(
        om_db,
        f"SELECT content FROM memories "
        f"WHERE tags LIKE '%tool-learning%' AND tags NOT LIKE '%bootstrap%' "
        f"ORDER BY {decay_score} DESC LIMIT 5;",
    )

    if learnings:
        print("")
        print("=== MEMORY SNAPSHOT (mandatory context) ===")
        print("  Tool learnings:")
        for row in learnings:
            print(f"    - {trunc(row[0])}")
        print("=== END MEMORY SNAPSHOT ===")


def main():
    om_db = sys.argv[1]
    prune_and_query(om_db)


if __name__ == "__main__":
    main()
