#!/usr/bin/env python3
"""One-time OpenMemory dedup cleanup. Removes duplicate corrections,
transcripts, and prompt-patterns, keeping the highest-salience entry per group."""

import argparse
import os
import sqlite3
from difflib import SequenceMatcher


DB_PATH = os.path.expanduser("~/.claude/.claude/openmemory.sqlite")


def group_by_similarity(entries, threshold):
    """Group entries by content similarity. Returns list of groups (lists of rows)."""
    groups = []
    used = set()
    for i, (id_a, content_a, salience_a) in enumerate(entries):
        if id_a in used:
            continue
        group = [(id_a, content_a, salience_a)]
        used.add(id_a)
        for j in range(i + 1, len(entries)):
            id_b, content_b, salience_b = entries[j]
            if id_b in used:
                continue
            ratio = SequenceMatcher(None, content_a, content_b).ratio()
            if ratio > threshold:
                group.append((id_b, content_b, salience_b))
                used.add(id_b)
        if len(group) > 1:
            groups.append(group)
    return groups


def find_deletions(groups):
    """For each group, keep the entry with highest salience, return IDs to delete."""
    to_delete = []
    for group in groups:
        best = max(group, key=lambda x: x[2] if x[2] is not None else 0)
        for entry in group:
            if entry[0] != best[0]:
                to_delete.append(entry[0])
    return to_delete


def run_pass(cursor, label, tag_filter, threshold, where_extra=""):
    """Run one dedup pass. Returns (scanned, groups_found, ids_to_delete)."""
    where = f"tags LIKE '%{tag_filter}%'"
    if where_extra:
        where += f" AND {where_extra}"
    cursor.execute(
        f"SELECT id, content, salience FROM memories WHERE {where} ORDER BY id"
    )
    entries = cursor.fetchall()
    groups = group_by_similarity(entries, threshold)
    to_delete = find_deletions(groups)

    print(f"\n--- {label} ---")
    print(f"  Scanned:  {len(entries)}")
    print(f"  Groups:   {len(groups)}")
    print(f"  To delete: {len(to_delete)}")
    print(f"  Retained: {len(entries) - len(to_delete)}")

    if groups:
        for i, group in enumerate(groups, 1):
            best = max(group, key=lambda x: x[2] if x[2] is not None else 0)
            print(f"  Group {i}: {len(group)} entries, keeping {best[0][:12]}... "
                  f"(salience={best[2]})")
            for entry in group:
                if entry[0] != best[0]:
                    preview = entry[1][:80].replace("\n", " ")
                    print(f"    DEL {entry[0][:12]}... \"{preview}\"")

    return entries, groups, to_delete


def main():
    parser = argparse.ArgumentParser(description="Deduplicate OpenMemory entries")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                       help="Show what would be deleted (default)")
    mode.add_argument("--execute", action="store_true",
                       help="Actually delete duplicates")
    args = parser.parse_args()
    execute = args.execute

    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    all_deletions = []

    # Pass 1: Correction duplicates
    _, _, dels = run_pass(cursor, "Correction duplicates", "correction", 0.8)
    all_deletions.extend(dels)

    # Pass 2: Transcript duplicates (episodic sector)
    _, _, dels = run_pass(cursor, "Transcript duplicates", "transcript", 0.8,
                          where_extra="primary_sector = 'episodic'")
    all_deletions.extend(dels)

    # Pass 3: Prompt-pattern duplicates (global scope, lower threshold)
    _, _, dels = run_pass(cursor, "Prompt-pattern duplicates", "prompt-pattern", 0.7,
                          where_extra="user_id = 'global'")
    all_deletions.extend(dels)

    print(f"\n=== TOTAL ===")
    print(f"  Entries to delete: {len(all_deletions)}")
    print(f"  Mode: {'EXECUTE' if execute else 'DRY RUN'}")

    if execute and all_deletions:
        placeholders = ",".join("?" for _ in all_deletions)
        cursor.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", all_deletions)
        cursor.execute(f"DELETE FROM vectors WHERE id IN ({placeholders})", all_deletions)
        conn.commit()
        print(f"\n  Deleted {len(all_deletions)} entries:")
        for did in all_deletions:
            print(f"    {did}")
    elif execute:
        print("\n  Nothing to delete.")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
