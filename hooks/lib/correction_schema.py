"""Shared DDL for the correction_groups table."""

CORRECTION_GROUPS_DDL = (
    "CREATE TABLE IF NOT EXISTS correction_groups ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "theme TEXT NOT NULL, "
    "status TEXT DEFAULT 'accumulating' CHECK(status IN ('accumulating','pending_promotion','promoted','dismissed')), "
    "count INTEGER DEFAULT 1, "
    "correction_dates TEXT DEFAULT '[]', "
    "embedding BLOB, "
    "promoted_at TEXT, "
    "created_at INTEGER, "
    "updated_at INTEGER, "
    "source TEXT DEFAULT 'auto', "
    "text TEXT DEFAULT '')",
    "CREATE INDEX IF NOT EXISTS idx_correction_groups_status ON correction_groups(status)",
)
