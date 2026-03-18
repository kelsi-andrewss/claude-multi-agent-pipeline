#!/usr/bin/env python3
"""Generate a decisions.sql dump from scout bootstrap JSON output.

Reads explore agent JSON from stdin, emits SQL to stdout.
Uses the same format and helpers as decision_memory.dump.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def _sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _sql_int(value: int | None) -> str:
    if value is None:
        return "NULL"
    return str(value)


_VALID_SCOPE_TYPES = frozenset({"file", "pattern", "tech"})


def generate(data: dict, target_path: str = "") -> str:
    lines: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    lines.append("-- decision_memory dump v1")
    lines.append(f"-- generated {now}")
    if target_path:
        lines.append(f"-- source: /scout --bootstrap {target_path}")
    lines.append("")

    lines.append(
        "CREATE TABLE IF NOT EXISTS decisions (\n"
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    content TEXT NOT NULL,\n"
        "    reasoning TEXT,\n"
        "    positive_framing TEXT,\n"
        "    status TEXT NOT NULL DEFAULT 'active'\n"
        "        CHECK (status IN ('active', 'deprecated', 'superseded', 'violated')),\n"
        "    source TEXT NOT NULL DEFAULT 'human'\n"
        "        CHECK (source IN ('human', 'ai-discovered', 'ai-proposed')),\n"
        "    superseded_by INTEGER REFERENCES decisions(id),\n"
        "    created_at TEXT NOT NULL DEFAULT (datetime('now')),\n"
        "    updated_at TEXT NOT NULL DEFAULT (datetime('now'))\n"
        ");"
    )
    lines.append("")

    lines.append(
        "CREATE TABLE IF NOT EXISTS decision_scopes (\n"
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,\n"
        "    scope_type TEXT NOT NULL CHECK (scope_type IN ('file', 'pattern', 'tech')),\n"
        "    scope_value TEXT NOT NULL\n"
        ");"
    )
    lines.append("")

    decisions = data.get("architectural_decisions", [])
    scope_id = 1

    for idx, dec in enumerate(decisions, start=1):
        content = dec.get("content", "")
        reasoning = dec.get("reasoning", "")
        lines.append(
            f"INSERT OR REPLACE INTO decisions "
            f"(id, content, reasoning, status, source, superseded_by, created_at, updated_at) "
            f"VALUES ({idx}, {_sql_str(content)}, {_sql_str(reasoning)}, "
            f"'active', 'ai-discovered', NULL, {_sql_str(now)}, {_sql_str(now)});"
        )

    if decisions:
        lines.append("")

    for idx, dec in enumerate(decisions, start=1):
        scope_type = dec.get("scope_type", "tech")
        if scope_type not in _VALID_SCOPE_TYPES:
            scope_type = "tech"
        scope_value = dec.get("scope_value", "")
        lines.append(
            f"INSERT OR REPLACE INTO decision_scopes "
            f"(id, decision_id, scope_type, scope_value) "
            f"VALUES ({scope_id}, {idx}, {_sql_str(scope_type)}, {_sql_str(scope_value)});"
        )
        scope_id += 1

    if decisions:
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    data = json.load(sys.stdin)
    print(generate(data, target))
