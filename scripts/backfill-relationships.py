#!/usr/bin/env python3
"""Backfill known decision relationships into decisions.db.

Usage:
    python3 backfill-relationships.py [--project-root <path>] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

# (source_id, target_id) -- direction matters for depends_on/constrains
DEPENDS_ON = [(21, 24), (24, 6), (7, 8), (8, 4), (12, 6), (14, 12), (15, 10), (23, 21), (23, 22)]
CONSTRAINS = [(6, 7), (6, 12), (13, 3), (19, 17), (19, 18), (6, 25)]
# Bidirectional
RELATED = [(9, 10), (9, 11), (10, 11), (21, 22), (21, 23), (22, 23), (12, 13), (12, 14), (13, 14), (17, 18), (17, 19), (18, 19), (7, 8)]


def _merge_relationships(existing: str | None, new_entry: str) -> str:
    """Append new_entry to existing comma-separated relationships, deduplicating by (id, type)."""
    seen: set[str] = set()
    if existing and existing.strip():
        for token in existing.split(","):
            token = token.strip()
            if token:
                seen.add(token)
    new_entry = new_entry.strip()
    if new_entry:
        seen.add(new_entry)
    return ",".join(sorted(seen))


def build_relationship_map() -> dict[int, list[str]]:
    """Build per-decision-id list of relationship entries from the known tuples."""
    rels: dict[int, list[str]] = {}

    for source, target in DEPENDS_ON:
        rels.setdefault(source, []).append(f"{target}:depends_on")

    for source, target in CONSTRAINS:
        rels.setdefault(source, []).append(f"{target}:constrains")

    for a, b in RELATED:
        rels.setdefault(a, []).append(f"{b}:related")
        rels.setdefault(b, []).append(f"{a}:related")

    return rels


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill known decision relationships")
    parser.add_argument(
        "--project-root", type=str,
        default=os.path.expanduser("~/.claude"),
        help="Project root containing .claude/decisions.db",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without writing to DB",
    )
    args = parser.parse_args()

    db_path = Path(args.project_root) / ".claude" / "decisions.db"
    if not db_path.exists():
        print(json.dumps({"status": "error", "message": f"Database not found: {db_path}"}))
        sys.exit(1)

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Ensure related_decisions column exists
    cols = conn.execute("PRAGMA table_info(decisions)").fetchall()
    col_names = {c[1] for c in cols}
    has_column = "related_decisions" in col_names
    if not has_column:
        if args.dry_run:
            print("DRY RUN: Would ALTER TABLE decisions ADD COLUMN related_decisions TEXT")
        else:
            conn.execute("ALTER TABLE decisions ADD COLUMN related_decisions TEXT")
            conn.commit()
            has_column = True

    rel_map = build_relationship_map()
    updated = 0
    skipped = 0

    for decision_id, entries in sorted(rel_map.items()):
        # Check decision exists
        exists_row = conn.execute(
            "SELECT id FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()

        if exists_row is None:
            skipped += 1
            if args.dry_run:
                print(f"DRY RUN: Decision {decision_id} not found in DB, skipping")
            continue

        if has_column:
            row = conn.execute(
                "SELECT related_decisions FROM decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()
            existing = row[0] if row else None
        else:
            existing = None
        merged = existing
        for entry in entries:
            merged = _merge_relationships(merged, entry)

        if merged == existing:
            skipped += 1
            if args.dry_run:
                print(f"DRY RUN: Decision {decision_id} already has all relationships, skipping")
            continue

        if args.dry_run:
            print(f"DRY RUN: Decision {decision_id}: {existing!r} -> {merged!r}")
        else:
            conn.execute(
                "UPDATE decisions SET related_decisions = ? WHERE id = ?",
                (merged, decision_id),
            )
        updated += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(json.dumps({"status": "backfilled" if not args.dry_run else "dry_run", "updated": updated, "skipped": skipped}))


if __name__ == "__main__":
    main()
