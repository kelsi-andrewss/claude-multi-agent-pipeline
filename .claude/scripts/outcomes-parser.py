#!/usr/bin/env python3
"""Parse outcomes.md into structured records and populate merge_outcomes table.

Usage: python3 outcomes-parser.py [--outcomes-path PATH] [--db-path PATH] [--dry-run]

Reads outcomes.md, splits on ## headings, extracts fields per entry,
and upserts into run-state.db merge_outcomes table keyed on story_id.
"""
import argparse
import json
import os
import re
import sqlite3
import sys

DEFAULT_OUTCOMES_PATH = os.path.expanduser("~/.claude/outcomes.md")
DEFAULT_DB_PATH = os.path.expanduser("~/.claude/.claude/run-state.db")

AGENT_NORMALIZE = {
    "arch": "architect",
    "qf": "quick-fixer",
}

HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s+--\s+(story-\d+)\s+--\s+(.*)$")
FIELD_RE = re.compile(r"^\*\*([^*]+)\*\*:\s*(.*)$")


def parse_cycle_time(raw):
    """Parse cycle time string to seconds. Returns None if unparseable."""
    raw = raw.strip().lower()
    if raw in ("unknown", "n/a", "not captured", ""):
        return None

    raw = raw.lstrip("~<>")

    m = re.match(r"([\d.]+)\s*h", raw)
    if m:
        return int(float(m.group(1)) * 3600)

    m = re.match(r"([\d.]+)\s*min", raw)
    if m:
        return int(float(m.group(1)) * 60)

    m = re.match(r"([\d.]+)\s*s$", raw)
    if m:
        return int(float(m.group(1)))

    return None


def parse_friction_count(raw):
    """Extract friction event count from string like '0 (clean)' or '1: blocked (...)'."""
    raw = raw.strip()
    m = re.match(r"(\d+)", raw)
    if m:
        return int(m.group(1))
    return 0


def normalize_agent(raw):
    """Normalize agent field to canonical name."""
    raw = raw.strip().lower()
    return AGENT_NORMALIZE.get(raw, raw)


def extract_model(raw):
    """Extract model name (first word) from model field."""
    raw = raw.strip().lower()
    first = raw.split()[0] if raw else ""
    for known in ("haiku", "sonnet", "opus"):
        if known in first:
            return known
    return first or None


def parse_outcomes(outcomes_path):
    """Parse outcomes.md into structured records.

    Returns list of dicts with: story_id, epic_id, agent, model, success,
    cycle_time_s, revert_count, domain_tags, what_worked, what_failed,
    predicted_conflict, actual_conflict.
    """
    with open(outcomes_path) as f:
        content = f.read()

    sections = re.split(r"(?=^## \d{4})", content, flags=re.MULTILINE)

    records = []
    for section in sections:
        section = section.strip()
        if not section:
            continue

        lines = section.split("\n")
        heading_match = HEADING_RE.match(lines[0])
        if not heading_match:
            continue

        story_id = heading_match.group(2)

        fields = {}
        for line in lines[1:]:
            fm = FIELD_RE.match(line.strip())
            if fm:
                fields[fm.group(1).strip()] = fm.group(2).strip()

        result_raw = fields.get("Result", "").lower()
        success = result_raw.startswith("merged")

        agent = normalize_agent(fields.get("Agent", ""))
        model = extract_model(fields.get("Model", ""))
        cycle_time_s = parse_cycle_time(fields.get("Cycle time", ""))

        friction_count = parse_friction_count(fields.get("Friction events", "0"))

        skills_raw = fields.get("Skills used", "")
        domain_tags = [s.strip() for s in skills_raw.split(",") if s.strip()] if skills_raw else []

        what_worked = fields.get("What worked", "")
        what_failed = fields.get("What failed", "")

        records.append({
            "story_id": story_id,
            "epic_id": None,
            "agent": agent or None,
            "model": model or None,
            "success": success,
            "cycle_time_s": cycle_time_s,
            "revert_count": friction_count,
            "domain_tags": json.dumps(domain_tags),
            "predicted_conflict": None,
            "actual_conflict": None,
            "what_worked": what_worked,
            "what_failed": what_failed,
        })

    return records


def populate_merge_outcomes(db_path, records):
    """Insert/upsert records into merge_outcomes table. Returns count inserted."""
    conn = sqlite3.connect(db_path, timeout=10)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")

    # Migrate new columns (idempotent)
    for col in [
        "what_worked TEXT",
        "what_failed TEXT",
        "friction_events INTEGER DEFAULT 0",
        "file_count INTEGER",
        "complexity TEXT",
        "skills_used TEXT",
        "coder_effort TEXT",
        "memory_attributed TEXT",
    ]:
        try:
            cursor.execute(f"ALTER TABLE merge_outcomes ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass

    inserted = 0
    for rec in records:
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO merge_outcomes "
                "(story_id, epic_id, agent, model, domain_tags, predicted_conflict, "
                "actual_conflict, success, cycle_time_s, revert_count, "
                "what_worked, what_failed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec["story_id"],
                    rec["epic_id"],
                    rec["agent"],
                    rec["model"],
                    rec["domain_tags"],
                    rec["predicted_conflict"],
                    rec["actual_conflict"],
                    rec["success"],
                    rec["cycle_time_s"],
                    rec["revert_count"],
                    rec.get("what_worked"),
                    rec.get("what_failed"),
                ),
            )
            if cursor.rowcount > 0:
                inserted += 1
        except sqlite3.Error as e:
            print(f"Insert failed for {rec['story_id']}: {e}", file=sys.stderr)

    conn.commit()
    conn.close()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Parse outcomes.md into merge_outcomes table")
    parser.add_argument("--outcomes-path", default=DEFAULT_OUTCOMES_PATH, help="Path to outcomes.md")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path to run-state.db")
    parser.add_argument("--dry-run", action="store_true", help="Print parsed records without DB writes")
    args = parser.parse_args()

    if not os.path.isfile(args.outcomes_path):
        print(json.dumps({"error": f"outcomes file not found: {args.outcomes_path}"}))
        sys.exit(1)

    records = parse_outcomes(args.outcomes_path)

    if args.dry_run:
        print(json.dumps({"parsed": len(records), "records": records}, indent=2))
        return

    if not os.path.isfile(args.db_path):
        print(json.dumps({"error": f"database not found: {args.db_path}"}))
        sys.exit(1)

    inserted = populate_merge_outcomes(args.db_path, records)
    print(json.dumps({"parsed": len(records), "inserted": inserted}))


if __name__ == "__main__":
    main()
