from __future__ import annotations

DECISIONS_DDL = """\
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    reasoning TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deprecated', 'superseded', 'violated')),
    source TEXT NOT NULL DEFAULT 'human'
        CHECK (source IN ('human', 'ai-discovered', 'ai-proposed')),
    superseded_by INTEGER REFERENCES decisions(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    domain TEXT,
    related_decisions TEXT
)"""

SCOPES_DDL = """\
CREATE TABLE IF NOT EXISTS decision_scopes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('file', 'pattern', 'tech')),
    scope_value TEXT NOT NULL
)"""

DUMP_DDL = DECISIONS_DDL + ";\n\n" + SCOPES_DDL + ";"

METADATA_DDL = """\
CREATE TABLE IF NOT EXISTS _metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);"""

FTS_DDL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    content, reasoning, content=decisions, content_rowid=id
);"""

VEC_DDL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS decision_embeddings USING vec0(
    decision_id integer primary key,
    embedding float[256]
);"""

DUMP_VERSION = 3

VALID_SCOPE_TYPES = frozenset({"file", "pattern", "tech"})


def sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    clean = value.replace("\x00", "")
    escaped = clean.replace("'", "''")
    return f"'{escaped}'"


def sql_int(value: int | None) -> str:
    if value is None:
        return "NULL"
    return str(value)
