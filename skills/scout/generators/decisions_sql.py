#!/usr/bin/env python3
"""Generate a decisions.sql dump from scout bootstrap JSON output.

Reads explore agent JSON from stdin, emits SQL to stdout.
Uses the same format and helpers as decision_memory.dump.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from decision_memory.schema import (
    DECISIONS_DDL,
    DUMP_VERSION,
    SCOPES_DDL,
    VALID_SCOPE_TYPES,
    sql_str,
)


def generate(data: dict, target_path: str = "") -> str:
    lines: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    lines.append(f"-- decision_memory dump v{DUMP_VERSION}")
    lines.append(f"-- generated {now}")
    if target_path:
        lines.append(f"-- source: /scout --bootstrap {target_path}")
    lines.append("")

    lines.append(DECISIONS_DDL + ";")
    lines.append("")

    lines.append(SCOPES_DDL + ";")
    lines.append("")

    decisions = data.get("architectural_decisions", [])
    scope_id = 1

    for idx, dec in enumerate(decisions, start=1):
        content = dec.get("content", "")
        reasoning = dec.get("reasoning", "")
        lines.append(
            f"INSERT OR REPLACE INTO decisions "
            f"(id, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions) "
            f"VALUES ({idx}, {sql_str(content)}, {sql_str(reasoning)}, "
            f"'active', 'ai-discovered', NULL, {sql_str(now)}, {sql_str(now)}, NULL, NULL);"
        )

    if decisions:
        lines.append("")

    for idx, dec in enumerate(decisions, start=1):
        scope_type = dec.get("scope_type", "tech")
        if scope_type not in VALID_SCOPE_TYPES:
            scope_type = "tech"
        scope_value = dec.get("scope_value", "")
        lines.append(
            f"INSERT OR REPLACE INTO decision_scopes "
            f"(id, decision_id, scope_type, scope_value) "
            f"VALUES ({scope_id}, {idx}, {sql_str(scope_type)}, {sql_str(scope_value)});"
        )
        scope_id += 1

    if decisions:
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    data = json.load(sys.stdin)
    print(generate(data, target))
