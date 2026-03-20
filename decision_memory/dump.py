from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .schema import DECISIONS_DDL, DUMP_VERSION, SCOPES_DDL, sql_int, sql_str

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
    lines.append(f"-- decision_memory dump v{DUMP_VERSION}")
    lines.append(f"-- generated {datetime.now(timezone.utc).isoformat()}")
    lines.append("")

    lines.append(DECISIONS_DDL + ";")
    lines.append("")

    lines.append(SCOPES_DDL + ";")
    lines.append("")

    for row in decisions:
        did, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions = row
        lines.append(
            f"INSERT OR REPLACE INTO decisions (id, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions) "
            f"VALUES ({did}, {sql_str(content)}, {sql_str(reasoning)}, {sql_str(status)}, "
            f"{sql_str(source)}, {sql_int(superseded_by)}, {sql_str(created_at)}, {sql_str(updated_at)}, {sql_str(domain)}, {sql_str(related_decisions)});"
        )

    if decisions:
        lines.append("")

    for row in scopes:
        sid, decision_id, scope_type, scope_value = row
        lines.append(
            f"INSERT OR REPLACE INTO decision_scopes (id, decision_id, scope_type, scope_value) "
            f"VALUES ({sid}, {decision_id}, {sql_str(scope_type)}, {sql_str(scope_value)});"
        )

    if scopes:
        lines.append("")

    tmp_path = dump_path.with_suffix(".sql.tmp")
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text("\n".join(lines), encoding="utf-8")
    os.replace(str(tmp_path), str(dump_path))

    store.update_dump_hash()
