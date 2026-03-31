from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import sys
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


def _compute_scope_overlap(new_patterns: set[str], existing_patterns: set[str]) -> float:
    if not new_patterns and not existing_patterns:
        return 0.0
    intersection = new_patterns & existing_patterns
    return len(intersection) / max(len(new_patterns), len(existing_patterns))


def _merge_relationships(existing: str | None, new_entry: str) -> str:
    seen: set[str] = set()
    if existing and existing.strip():
        for token in existing.split(","):
            token = token.strip()
            if token:
                seen.add(token)
    new_entry = new_entry.strip()
    if new_entry:
        seen.add(new_entry)
    return ",".join(sorted(seen))


class DecisionStore:
    _vec_warned: bool = False

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.dump_path = project_root / ".claude" / "decisions.sql"
        self.db_path = project_root / ".claude" / "decisions.db"
        self._vec_available: bool | None = None

    def ensure_ready(self) -> None:
        if self._is_stale():
            self.sync_from_dump()

    def sync_from_dump(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.db_path.with_suffix(".db.tmp")
        conn = sqlite3.connect(str(tmp_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
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
        os.replace(str(tmp_path), str(self.db_path))
        for suffix in ("-shm", "-wal"):
            p = Path(str(self.db_path) + suffix)
            if p.exists():
                p.unlink()

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
            rows = conn.execute(
                "SELECT d.id, d.content, d.reasoning, d.status, d.source, d.superseded_by, "
                "d.created_at, d.updated_at, d.domain, d.related_decisions, "
                "s.id, s.decision_id, s.scope_type, s.scope_value "
                "FROM decisions d LEFT JOIN decision_scopes s ON s.decision_id = d.id "
                "WHERE d.id = ? ORDER BY s.id",
                (decision_id,),
            ).fetchall()
            if not rows:
                return None
            return self._rows_to_decisions(rows)[0]
        finally:
            conn.close()

    def list_all(self, status: str | None = None) -> list[Decision]:
        self.ensure_ready()
        conn = self._get_connection()
        try:
            query = (
                "SELECT d.id, d.content, d.reasoning, d.status, d.source, d.superseded_by, "
                "d.created_at, d.updated_at, d.domain, d.related_decisions, "
                "s.id, s.decision_id, s.scope_type, s.scope_value "
                "FROM decisions d LEFT JOIN decision_scopes s ON s.decision_id = d.id"
            )
            if status is not None:
                query += " WHERE d.status = ?"
                query += " ORDER BY d.id, s.id"
                rows = conn.execute(query, (status,)).fetchall()
            else:
                query += " ORDER BY d.id, s.id"
                rows = conn.execute(query).fetchall()
            return self._rows_to_decisions(rows)
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
        self._check_vec_status()

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

    def _check_vec_status(self) -> None:
        if self._vec_available is False and not DecisionStore._vec_warned:
            print(
                "decision_memory: sqlite-vec unavailable — vector search disabled",
                file=sys.stderr,
            )
            DecisionStore._vec_warned = True

    @staticmethod
    def _rows_to_decisions(rows: list[tuple]) -> list[Decision]:
        decisions: dict[int, Decision] = {}
        for row in rows:
            did = row[0]
            if did not in decisions:
                decisions[did] = Decision(
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
                    scopes=[],
                )
            if row[10] is not None:
                decisions[did].scopes.append(
                    DecisionScope(
                        id=row[10],
                        decision_id=row[11],
                        scope_type=row[12],
                        scope_value=row[13],
                    )
                )
        return list(decisions.values())

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

    def get_connection(self) -> sqlite3.Connection:
        return self._get_connection()

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

    def process_scope_overlap(
        self, decision_id: int, new_patterns: set[str]
    ) -> tuple[list[int], list[str]]:
        """Check active decisions for scope overlap and auto-supersede/relate.

        Returns (superseded_ids, warnings).
        """
        existing = self.list_all(status="active")
        superseded_ids: list[int] = []
        warnings: list[str] = []
        related_entries: list[str] = []
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            for existing_d in existing:
                if existing_d.id == decision_id:
                    continue
                existing_patterns = {
                    s.scope_value for s in existing_d.scopes if s.scope_type == "file"
                }
                overlap = _compute_scope_overlap(new_patterns, existing_patterns)
                if overlap > 0.5:
                    conn.execute(
                        "UPDATE decisions SET status = 'superseded', superseded_by = ?, updated_at = ? WHERE id = ?",
                        (decision_id, now, existing_d.id),
                    )
                    superseded_ids.append(existing_d.id)
                elif overlap > 0:
                    warnings.append(
                        f"decision-{existing_d.id} has partial scope overlap ({overlap:.0%})"
                    )
                    related_entries.append(f"{existing_d.id}:related")
                    merged = _merge_relationships(existing_d.related_decisions, f"{decision_id}:related")
                    conn.execute(
                        "UPDATE decisions SET related_decisions = ?, updated_at = ? WHERE id = ?",
                        (merged, now, existing_d.id),
                    )
            if related_entries:
                new_rels = None
                for entry in related_entries:
                    new_rels = _merge_relationships(new_rels, entry)
                conn.execute(
                    "UPDATE decisions SET related_decisions = ?, updated_at = ? WHERE id = ?",
                    (new_rels, now, decision_id),
                )
            conn.commit()
        finally:
            conn.close()
        return superseded_ids, warnings

    def rebuild_index(self, provider: "EmbeddingProvider") -> int:
        """Rebuild the search index using the given embedding provider."""
        from .search import SearchEngine

        conn = self._get_connection()
        try:
            engine = SearchEngine(conn, provider)
            count = engine.rebuild_index()
            conn.commit()
            return count
        finally:
            conn.close()

    def search(self, query_text: str, provider: "EmbeddingProvider", limit: int = 5) -> list:
        """Run hybrid search and return SearchResult list."""
        from .search import SearchEngine

        conn = self._get_connection()
        try:
            engine = SearchEngine(conn, provider)
            return engine.hybrid_search(query_text, limit=limit)
        finally:
            conn.close()

    def list_by_domain(self, domain: str, limit: int = 50) -> list[Decision]:
        """Return active decisions matching the given domain."""
        self.ensure_ready()
        conn = self._get_connection()
        try:
            columns = conn.execute("PRAGMA table_info(decisions)").fetchall()
            has_domain = any(col[1] == "domain" for col in columns)
            if not has_domain:
                return []

            escaped = domain.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = conn.execute(
                "SELECT id, content, reasoning, status, source, superseded_by, "
                "created_at, updated_at, domain, related_decisions FROM decisions "
                "WHERE status = 'active' AND (domain = ? OR domain LIKE ? ESCAPE '\\') "
                "ORDER BY id LIMIT ?",
                (domain, f"%{escaped}%", limit),
            ).fetchall()

            decisions = []
            for row in rows:
                scope_rows = conn.execute(
                    "SELECT id, decision_id, scope_type, scope_value "
                    "FROM decision_scopes WHERE decision_id = ?",
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
