#!/usr/bin/env python3
"""One-time OpenMemory cleanup script.

Usage: python3 scripts/om-cleanup.py [--wet]

Default: dry-run (prints what would be deleted without modifying the DB).
Pass --wet to actually delete entries.
"""
import os, sqlite3, sys

OM_DB_PATH = os.path.expanduser("~/.claude/.claude/openmemory.sqlite")


def run_cleanup(wet=False):
    if not os.path.isfile(OM_DB_PATH):
        print(f"Database not found: {OM_DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(OM_DB_PATH, timeout=10)
    cursor = conn.cursor()

    delete_ids = set()

    # 1. Corrections (not behavioral-pref)
    cursor.execute(
        "SELECT id FROM memories WHERE tags LIKE ? AND tags NOT LIKE ?",
        ("%correction%", "%behavioral-pref%"),
    )
    correction_ids = {row[0] for row in cursor.fetchall()}
    delete_ids |= correction_ids
    print(f"Corrections (non-behavioral-pref): {len(correction_ids)}")

    # 2. Auto-extracted
    cursor.execute(
        "SELECT id FROM memories WHERE tags LIKE ?",
        ("%auto-extracted%",),
    )
    auto_ids = {row[0] for row in cursor.fetchall()}
    delete_ids |= auto_ids
    print(f"Auto-extracted: {len(auto_ids)}")

    # 3. Transcripts
    cursor.execute(
        "SELECT id FROM memories WHERE tags LIKE ?",
        ("%transcript%",),
    )
    transcript_ids = {row[0] for row in cursor.fetchall()}
    delete_ids |= transcript_ids
    print(f"Transcripts: {len(transcript_ids)}")

    # 4. Empty content
    cursor.execute(
        "SELECT id FROM memories WHERE content = '' OR content IS NULL",
    )
    empty_ids = {row[0] for row in cursor.fetchall()}
    delete_ids |= empty_ids
    print(f"Empty content: {len(empty_ids)}")

    # 5. Duplicate tool-learnings by simhash (keep longest)
    cursor.execute(
        "SELECT id, simhash, LENGTH(content) as clen FROM memories "
        "WHERE tags LIKE ? AND simhash IS NOT NULL",
        ("%tool-learning%",),
    )
    tl_rows = cursor.fetchall()
    simhash_groups = {}
    for row_id, simhash, clen in tl_rows:
        if simhash not in simhash_groups:
            simhash_groups[simhash] = []
        simhash_groups[simhash].append((row_id, clen or 0))

    tl_dedup_count = 0
    for simhash, entries in simhash_groups.items():
        if len(entries) <= 1:
            continue
        entries.sort(key=lambda x: x[1], reverse=True)
        for row_id, _ in entries[1:]:
            delete_ids.add(row_id)
            tl_dedup_count += 1
    print(f"Tool-learning duplicates: {tl_dedup_count}")

    print(f"\nTotal to {'delete' if wet else 'delete (dry-run)'}: {len(delete_ids)}")

    if wet and delete_ids:
        for row_id in delete_ids:
            cursor.execute("DELETE FROM memories WHERE id = ?", (row_id,))
        conn.commit()
        print(f"Deleted {len(delete_ids)} entries.")
    elif not wet and delete_ids:
        print("Would delete entries (dry-run). Pass --wet to execute.")

    # Show what remains
    cursor.execute("SELECT COUNT(*) FROM memories")
    remaining = cursor.fetchone()[0]
    if wet:
        print(f"Remaining entries: {remaining}")
    else:
        print(f"Remaining entries after cleanup: {remaining - len(delete_ids)}")

    conn.close()


if __name__ == "__main__":
    wet = "--wet" in sys.argv
    run_cleanup(wet=wet)
