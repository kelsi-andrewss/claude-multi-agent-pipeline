from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .schema import DUMP_DDL, FTS_DDL, METADATA_DDL, VEC_DDL
from .types import Decision, DecisionScope

log = logging.getLogger(__name__)

_DOMAIN_PREFIX_MAP = [
    ("hooks/", "hooks"),
    ("mcp-servers/", "mcp"),
    ("scripts/", "scripts"),
    ("decision_memory/", "decision-memory"),
    ("skills/", "skills"),
]


def _derive_domain_from_scopes(scopes: list[DecisionScope]) -> str | None:
    file_scopes = [s for s in scopes if s.scope_type == "file"]
    if not file_scopes:
        return None
    domains: set[str] = set()
    for scope in file_scopes:
        matched = False
        for prefix, domain in _DOMAIN_PREFIX_MAP:
            if scope.scope_value.startswith(prefix):
                domains.add(domain)
                matched = True
                break
        if not matched:
            domains.add("general")
    return ",".join(sorted(domains)) if domains else "general"


class DecisionStore:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.dump_path = project_root / ".claude" / "decisions.sql"
        self.db_path = project_root / ".claude" / "decisions.db"
        self._vec_available: bool | None = None

    def ensure_ready(self) -> None:
        if self._is_stale():
            self.sync_from_dump()

    def sync_from_dump(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
            for suffix in ("-shm", "-wal"):
                p = self.db_path.parent / (self.db_path.name + suffix)
                if p.exists():
                    p.unlink()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection()
        try:
            dump_content = self._read_dump()
            if dump_content:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.executescript(dump_content)
                conn.execute("PRAGMA foreign_keys=ON")

            self._init_schema(conn)

            if dump_content:
                self._populate_fts(conn)

            dump_hash = self._compute_dump_hash()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
                ("dump_hash", dump_hash or ""),
            )
            conn.execute(
                "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
                ("last_rebuild", now),
            )
            conn.commit()
        finally:
            conn.close()

    def record(self, decision: Decision) -> int:
        self.ensure_ready()
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            domain = decision.domain
            if domain is None and decision.scopes:
                domain = _derive_domain_from_scopes(decision.scopes)
            cursor = conn.execute(
                "INSERT INTO decisions (content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision.content,
                    decision.reasoning,
                    decision.status,
                    decision.source,
                    decision.superseded_by,
                    now,
                    now,
                    domain,
                    decision.related_decisions,
                ),
            )
            decision_id = cursor.lastrowid

            for scope in decision.scopes:
                conn.execute(
                    "INSERT INTO decision_scopes (decision_id, scope_type, scope_value) VALUES (?, ?, ?)",
                    (decision_id, scope.scope_type, scope.scope_value),
                )

            conn.execute(
                "INSERT INTO decisions_fts (rowid, content, reasoning) VALUES (?, ?, ?)",
                (decision_id, decision.content, decision.reasoning),
            )

            conn.commit()
            return decision_id
        finally:
            conn.close()

    def get(self, decision_id: int) -> Decision | None:
        self.ensure_ready()
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT id, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions "
                "FROM decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()
            if row is None:
                return None

            scope_rows = conn.execute(
                "SELECT id, decision_id, scope_type, scope_value FROM decision_scopes WHERE decision_id = ?",
                (decision_id,),
            ).fetchall()

            scopes = [
                DecisionScope(id=s[0], decision_id=s[1], scope_type=s[2], scope_value=s[3])
                for s in scope_rows
            ]

            return Decision(
                id=row[0],
                content=row[1],
                reasoning=row[2],
                status=row[3],
                source=row[4],
                superseded_by=row[5],
                created_at=row[6],
                updated_at=row[7],
                domain=row[8],
                related_decisions=row[9],
                scopes=scopes,
            )
        finally:
            conn.close()

    def list_all(self, status: str | None = None) -> list[Decision]:
        self.ensure_ready()
        conn = self._get_connection()
        try:
            if status is not None:
                rows = conn.execute(
                    "SELECT id, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions "
                    "FROM decisions WHERE status = ? ORDER BY id",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, content, reasoning, status, source, superseded_by, created_at, updated_at, domain, related_decisions "
                    "FROM decisions ORDER BY id"
                ).fetchall()

            decisions = []
            for row in rows:
                scope_rows = conn.execute(
                    "SELECT id, decision_id, scope_type, scope_value FROM decision_scopes WHERE decision_id = ?",
                    (row[0],),
                ).fetchall()
                scopes = [
                    DecisionScope(id=s[0], decision_id=s[1], scope_type=s[2], scope_value=s[3])
                    for s in scope_rows
                ]
                decisions.append(
                    Decision(
                        id=row[0],
                        content=row[1],
                        reasoning=row[2],
                        status=row[3],
                        source=row[4],
                        superseded_by=row[5],
                        created_at=row[6],
                        updated_at=row[7],
                        domain=row[8],
                        related_decisions=row[9],
                        scopes=scopes,
                    )
                )
            return decisions
        finally:
            conn.close()

    def _compute_dump_hash(self) -> str | None:
        if not self.dump_path.exists():
            return None
        content = self.dump_path.read_bytes()
        return hashlib.sha256(content).hexdigest()

    def _is_stale(self) -> bool:
        if not self.db_path.exists():
            return True
        try:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT value FROM _metadata WHERE key = 'dump_hash'"
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.OperationalError:
            return True

        if row is None:
            return True

        current_hash = self._compute_dump_hash()
        stored_hash = row[0]
        return stored_hash != (current_hash or "")

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        self._migrate_v1_to_v2(conn)
        self._migrate_v2_to_v3(conn)
        conn.executescript(DUMP_DDL)
        conn.executescript(METADATA_DDL)
        conn.executescript(FTS_DDL)
        self._try_create_vec_table(conn)

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        try:
            cols = conn.execute("PRAGMA table_info(decisions)").fetchall()
        except sqlite3.OperationalError:
            return
        col_names = {c[1] for c in cols}
        if cols and "domain" not in col_names:
            conn.execute("ALTER TABLE decisions ADD COLUMN domain TEXT")

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        try:
            cols = conn.execute("PRAGMA table_info(decisions)").fetchall()
        except sqlite3.OperationalError:
            return
        col_names = {c[1] for c in cols}
        if cols and "related_decisions" not in col_names:
            conn.execute("ALTER TABLE decisions ADD COLUMN related_decisions TEXT")

    def _try_create_vec_table(self, conn: sqlite3.Connection) -> None:
        if self._vec_available is False:
            return
        try:
            import sqlite_vec

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            conn.executescript(VEC_DDL)
            self._vec_available = True
        except ImportError:
            log.warning("sqlite-vec not installed; vector search disabled")
            self._vec_available = False
        except (sqlite3.OperationalError, AttributeError) as e:
            log.warning("sqlite-vec unavailable: %s", e)
            self._vec_available = False

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        if self._vec_available:
            try:
                import sqlite_vec
                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
            except (ImportError, AttributeError, sqlite3.OperationalError):
                pass
        return conn

    def _read_dump(self) -> str | None:
        if not self.dump_path.exists():
            return None
        content = self.dump_path.read_text(encoding="utf-8").strip()
        return content or None

    def _populate_fts(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO decisions_fts (rowid, content, reasoning) "
            "SELECT id, content, reasoning FROM decisions"
        )

    def update_dump_hash(self) -> None:
        conn = self._get_connection()
        try:
            dump_hash = self._compute_dump_hash()
            conn.execute(
                "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
                ("dump_hash", dump_hash or ""),
            )
            conn.commit()
        finally:
            conn.close()
