#!/usr/bin/env python3
"""Render decision health scores (negative signals) by appending to sidecar.

Usage: python3 -m hooks.lib.session_render_health <db_path> <output_path>
"""
import sqlite3, sys


def render_health(db_path, out_path):
    conn = sqlite3.connect(db_path, timeout=5)
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='decision_preferences'"
    )
    if not cur.fetchone():
        conn.close()
        return
    cur.execute(
        "SELECT decision_type, context, signal_score FROM decision_preferences "
        "WHERE signal_score < 0 ORDER BY signal_score ASC LIMIT 10"
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return
    with open(out_path, "a") as f:
        f.write("\n\n# Decision Health\n\n")
        for decision_type, context, signal_score in rows:
            ctx = context[:80] + "..." if len(context) > 80 else context
            f.write(f"- {decision_type}: {ctx} (signal: {signal_score})\n")


def main():
    try:
        db_path = sys.argv[1]
        out_path = sys.argv[2]
        render_health(db_path, out_path)
    except Exception:
        pass


if __name__ == "__main__":
    main()
