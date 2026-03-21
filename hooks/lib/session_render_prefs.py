#!/usr/bin/env python3
"""Render behavioral preferences from correction_groups DB to sidecar file.

Usage: python3 -m hooks.lib.session_render_prefs <db_path> <output_path>
"""
import sqlite3, sys


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


def render_prefs(db_path, out_path):
    cols = query_db(db_path, "PRAGMA table_info(correction_groups);")
    col_names = [c[1] for c in cols if len(c) > 1]
    if "text" not in col_names:
        with open(out_path, "w") as f:
            f.write("# Behavioral Preferences\n\n_Schema migration pending._\n")
        return

    rows = query_db(
        db_path,
        "SELECT text FROM correction_groups "
        "WHERE (status IN ('promoted','pending_promotion') OR source='manual') "
        "AND status != 'dismissed' "
        "ORDER BY updated_at DESC;",
    )

    with open(out_path, "w") as f:
        f.write("# Behavioral Preferences\n\n")
        if rows:
            for row in rows:
                text = row[0].strip()
                if text:
                    f.write(f"- {text}\n")
        else:
            f.write("_No preferences recorded yet._\n")


def main():
    db_path = sys.argv[1]
    out_path = sys.argv[2]
    render_prefs(db_path, out_path)


if __name__ == "__main__":
    main()
