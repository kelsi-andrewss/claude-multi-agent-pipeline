from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import DecisionStore


def dump_to_sql(store: DecisionStore, dump_path: Path) -> None:
    store.ensure_ready()
    conn = store._get_connection()
    try:
        decisions = conn.execute(
            "SELECT id, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions "
            "FROM decisions ORDER BY id"
        ).fetchall()

        scopes = conn.execute(
            "SELECT id, decision_id, scope_type, scope_value "
            "FROM decision_scopes ORDER BY decision_id, id"
        ).fetchall()
    finally:
        conn.close()

    lines: list[str] = []
    lines.append(f"-- decision_memory dump v3")
    lines.append(f"-- generated {datetime.now(timezone.utc).isoformat()}")
    lines.append("")

    lines.append(
        "CREATE TABLE IF NOT EXISTS decisions (\n"
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    content TEXT NOT NULL,\n"
        "    reasoning TEXT,\n"
        "    status TEXT NOT NULL DEFAULT 'active'\n"
        "        CHECK (status IN ('active', 'deprecated', 'superseded', 'violated')),\n"
        "    source TEXT NOT NULL DEFAULT 'human'\n"
        "        CHECK (source IN ('human', 'ai-discovered', 'ai-proposed')),\n"
        "    superseded_by INTEGER REFERENCES decisions(id),\n"
        "    created_at TEXT NOT NULL DEFAULT (datetime('now')),\n"
        "    updated_at TEXT NOT NULL DEFAULT (datetime('now')),\n"
        "    domain TEXT,\n"
        "    related_decisions TEXT\n"
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

    for row in decisions:
        did, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions = row
        lines.append(
            f"INSERT OR REPLACE INTO decisions (id, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions) "
            f"VALUES ({did}, {_sql_str(content)}, {_sql_str(reasoning)}, {_sql_str(status)}, "
            f"{_sql_str(source)}, {_sql_int(superseded_by)}, {_sql_str(created_at)}, {_sql_str(updated_at)}, {_sql_str(domain)}, {_sql_str(related_decisions)});"
        )

    if decisions:
        lines.append("")

    for row in scopes:
        sid, decision_id, scope_type, scope_value = row
        lines.append(
            f"INSERT OR REPLACE INTO decision_scopes (id, decision_id, scope_type, scope_value) "
            f"VALUES ({sid}, {decision_id}, {_sql_str(scope_type)}, {_sql_str(scope_value)});"
        )

    if scopes:
        lines.append("")

    tmp_path = dump_path.with_suffix(".sql.tmp")
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text("\n".join(lines), encoding="utf-8")
    os.replace(str(tmp_path), str(dump_path))

    store.update_dump_hash()


def _sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _sql_int(value: int | None) -> str:
    if value is None:
        return "NULL"
    return str(value)
