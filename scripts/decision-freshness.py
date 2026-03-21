#!/usr/bin/env python3
"""Compute per-decision staleness scores and write to run-state.db.

Usage:
    python3 decision-freshness.py [--project-root <path>] [--half-life <days>] [--max-days <days>]
    python3 decision-freshness.py --reinforce <decision_id> [--project-root <path>]

Normal mode: reads decisions from .claude/decisions.db, checks git activity
for each scoped file, computes exponential-decay staleness, and writes
results to the decision_freshness table in run-state.db.

Reinforce mode: increments reinforcement_count for a decision, which
reduces its staleness score on the next computation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN_STATE_DB = os.path.expanduser("~/.claude/.claude/run-state.db")
DEFAULT_HALF_LIFE = 90
DEFAULT_MAX_DAYS = 365

FRESHNESS_DDL = [
    """CREATE TABLE IF NOT EXISTS decision_freshness (
        decision_id INTEGER PRIMARY KEY,
        staleness_score REAL NOT NULL,
        days_since_activity INTEGER NOT NULL,
        last_git_activity TEXT,
        computed_at TEXT NOT NULL,
        reinforcement_count INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE INDEX IF NOT EXISTS idx_freshness_score ON decision_freshness(staleness_score)""",
]


def compute_staleness(days: int, half_life: int, reinforcement_count: int) -> float:
    """Exponential decay: 0.0 = fresh, 1.0 = fully stale.

    Each reinforcement halves the effective days, making the decision
    appear fresher.
    """
    effective_days = days / (2 ** reinforcement_count)
    return 1.0 - math.exp(-0.693 * effective_days / half_life)


def get_last_git_activity(project_root: Path, file_path: str, since: str) -> str | None:
    """Return ISO date of most recent git commit touching file_path, or None."""
    try:
        result = subprocess.run(
            [
                "git", "-C", str(project_root),
                "log", "-1", "--follow", "--format=%aI",
                "--since", since,
                "--", file_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        date_str = result.stdout.strip()
        if date_str:
            return date_str
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def load_decisions(project_root: Path) -> list[tuple[int, str, str]]:
    """Load active decisions with their file scopes from decisions.db.

    Returns list of (decision_id, scope_value, created_at) tuples.
    A decision without file scopes gets a single entry with scope_value=''.
    """
    db_path = project_root / ".claude" / "decisions.db"
    if not db_path.exists():
        return []

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT d.id, COALESCE(ds.scope_value, ''), d.created_at "
            "FROM decisions d "
            "LEFT JOIN decision_scopes ds ON ds.decision_id = d.id AND ds.scope_type = 'file' "
            "WHERE d.status = 'active' "
            "ORDER BY d.id"
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    finally:
        conn.close()


def reinforce_decision(conn: sqlite3.Connection, decision_id: int) -> None:
    """Increment reinforcement_count for a decision."""
    existing = conn.execute(
        "SELECT reinforcement_count FROM decision_freshness WHERE decision_id = ?",
        (decision_id,),
    ).fetchone()

    if existing is not None:
        conn.execute(
            "UPDATE decision_freshness SET reinforcement_count = reinforcement_count + 1 "
            "WHERE decision_id = ?",
            (decision_id,),
        )
    else:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO decision_freshness "
            "(decision_id, staleness_score, days_since_activity, last_git_activity, computed_at, reinforcement_count) "
            "VALUES (?, 0.0, 0, NULL, ?, 1)",
            (decision_id, now),
        )
    conn.commit()


def emit(obj: dict) -> None:
    print(json.dumps(obj))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute decision staleness scores")
    parser.add_argument(
        "--project-root", type=str,
        default=os.path.expanduser("~/.claude"),
        help="Project root containing .claude/decisions.db",
    )
    parser.add_argument(
        "--half-life", type=int, default=DEFAULT_HALF_LIFE,
        help=f"Half-life in days for staleness decay (default: {DEFAULT_HALF_LIFE})",
    )
    parser.add_argument(
        "--max-days", type=int, default=DEFAULT_MAX_DAYS,
        help=f"Maximum lookback days for git activity (default: {DEFAULT_MAX_DAYS})",
    )
    parser.add_argument(
        "--reinforce", type=int, metavar="DECISION_ID",
        help="Reinforce a decision (reduce its staleness)",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root)

    conn = sqlite3.connect(RUN_STATE_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    for ddl in FRESHNESS_DDL:
        conn.execute(ddl)
    conn.commit()

    if args.reinforce is not None:
        reinforce_decision(conn, args.reinforce)
        row = conn.execute(
            "SELECT reinforcement_count FROM decision_freshness WHERE decision_id = ?",
            (args.reinforce,),
        ).fetchone()
        conn.close()
        emit({
            "status": "reinforced",
            "decision_id": args.reinforce,
            "reinforcement_count": row[0] if row else 0,
        })
        return

    decisions = load_decisions(project_root)
    if not decisions:
        conn.close()
        emit({"status": "no_decisions", "count": 0})
        return

    now = datetime.now(timezone.utc)
    since_date = (now - timedelta(days=365)).strftime("%Y-%m-%d")

    # Group scopes by decision_id
    decision_scopes: dict[int, list[tuple[str, str]]] = {}
    for decision_id, scope_value, created_at in decisions:
        decision_scopes.setdefault(decision_id, []).append((scope_value, created_at))

    results = []
    for decision_id, scopes in decision_scopes.items():
        created_at = scopes[0][1]
        file_paths = [s[0] for s in scopes if s[0]]

        # Find most recent git activity across all scoped files
        latest_activity: str | None = None
        for fp in file_paths:
            activity = get_last_git_activity(project_root, fp, since_date)
            if activity and (latest_activity is None or activity > latest_activity):
                latest_activity = activity

        # Determine days since last relevant activity
        if latest_activity:
            activity_dt = datetime.fromisoformat(latest_activity)
            if activity_dt.tzinfo is None:
                activity_dt = activity_dt.replace(tzinfo=timezone.utc)
            days = (now - activity_dt).days
        elif created_at:
            created_dt = datetime.fromisoformat(created_at)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            days = (now - created_dt).days
        else:
            days = args.max_days

        days = min(days, args.max_days)

        # Fetch existing reinforcement_count
        existing = conn.execute(
            "SELECT reinforcement_count FROM decision_freshness WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        reinforcement_count = existing[0] if existing else 0

        score = compute_staleness(days, args.half_life, reinforcement_count)

        conn.execute(
            "INSERT OR REPLACE INTO decision_freshness "
            "(decision_id, staleness_score, days_since_activity, last_git_activity, computed_at, reinforcement_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (decision_id, round(score, 4), days, latest_activity,
             now.isoformat(), reinforcement_count),
        )

        results.append({
            "decision_id": decision_id,
            "staleness_score": round(score, 4),
            "days_since_activity": days,
            "reinforcement_count": reinforcement_count,
        })

    conn.commit()
    conn.close()

    stale_count = sum(1 for r in results if r["staleness_score"] > 0.7)
    emit({
        "status": "computed",
        "total": len(results),
        "stale_count": stale_count,
        "decisions": results,
    })


if __name__ == "__main__":
    main()
