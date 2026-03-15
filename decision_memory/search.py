from __future__ import annotations

import logging
import sqlite3
import struct
from datetime import datetime, timezone

from .embeddings import EmbeddingProvider
from .types import Decision, DecisionScope, SearchResult

log = logging.getLogger(__name__)


class SearchEngine:
    RRF_K = 60

    def __init__(
        self, conn: sqlite3.Connection, provider: EmbeddingProvider | None = None
    ) -> None:
        self._conn = conn
        self._provider = provider if provider is not None else EmbeddingProvider()

    def rebuild_index(self) -> int:
        rows = self._conn.execute(
            "SELECT id, content, reasoning FROM decisions WHERE status = 'active'"
        ).fetchall()

        if not rows:
            return 0

        ids = [r[0] for r in rows]
        texts = [f"{r[1]}\n{r[2] or ''}" for r in rows]

        embeddings = self._provider.get_embeddings_batch(texts)

        self._conn.execute("DELETE FROM decisions_fts")
        for row in rows:
            self._conn.execute(
                "INSERT INTO decisions_fts(rowid, content, reasoning) VALUES (?, ?, ?)",
                (row[0], row[1], row[2]),
            )

        if self._has_vec_table():
            self._conn.execute("DELETE FROM decision_embeddings")
            for i, emb in enumerate(embeddings):
                if emb is not None:
                    blob = struct.pack(f"<{len(emb.vector)}f", *emb.vector)
                    self._conn.execute(
                        "INSERT INTO decision_embeddings(decision_id, embedding) VALUES (?, ?)",
                        (ids[i], blob),
                    )

        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
            ("model_name", self._provider._model_name),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
            ("embedding_dim", str(self._provider._dim)),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
            ("index_count", str(len(rows))),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
            ("index_timestamp", now),
        )
        self._conn.commit()

        return len(rows)

    def hybrid_search(self, query: str, limit: int = 5) -> list[SearchResult]:
        fetch_limit = limit * 3

        vec_results = self.vector_search(query, limit=fetch_limit)
        kw_results = self.keyword_search(query, limit=fetch_limit)

        vec_ranks: dict[int, int] = {}
        vec_decisions: dict[int, Decision] = {}
        for rank, sr in enumerate(vec_results, start=1):
            did = sr.decision.id
            vec_ranks[did] = rank
            vec_decisions[did] = sr.decision

        kw_ranks: dict[int, int] = {}
        kw_decisions: dict[int, Decision] = {}
        for rank, sr in enumerate(kw_results, start=1):
            did = sr.decision.id
            kw_ranks[did] = rank
            kw_decisions[did] = sr.decision

        all_ids = set(vec_ranks.keys()) | set(kw_ranks.keys())
        if not all_ids:
            return []

        fused: list[SearchResult] = []
        for did in all_ids:
            score = 0.0
            in_vec = did in vec_ranks
            in_kw = did in kw_ranks

            if in_vec:
                score += 1.0 / (self.RRF_K + vec_ranks[did])
            if in_kw:
                score += 1.0 / (self.RRF_K + kw_ranks[did])

            if in_vec and in_kw:
                match_type = "hybrid"
            elif in_vec:
                match_type = "vector"
            else:
                match_type = "keyword"

            decision = vec_decisions.get(did) or kw_decisions[did]
            fused.append(SearchResult(decision=decision, score=score, match_type=match_type))

        fused.sort(key=lambda r: r.score, reverse=True)
        return fused[:limit]

    def vector_search(self, query: str, limit: int = 15) -> list[SearchResult]:
        if not self._has_vec_table():
            return []

        emb = self._provider.get_embedding(query)
        if emb is None:
            return []

        dim = len(emb.vector)
        query_blob = struct.pack(f"<{dim}f", *emb.vector)

        try:
            rows = self._conn.execute(
                "SELECT decision_id, distance FROM decision_embeddings "
                "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (query_blob, limit),
            ).fetchall()
        except sqlite3.OperationalError as e:
            log.warning("Vector search failed: %s", e)
            return []

        results: list[SearchResult] = []
        for decision_id, distance in rows:
            decision = self._fetch_decision(decision_id)
            if decision is None:
                continue
            score = 1.0 / (1.0 + distance)
            results.append(SearchResult(decision=decision, score=score, match_type="vector"))

        return results

    def keyword_search(self, query: str, limit: int = 15) -> list[SearchResult]:
        try:
            rows = self._conn.execute(
                "SELECT rowid, rank FROM decisions_fts "
                "WHERE decisions_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError as e:
            log.warning("FTS5 search failed (bad syntax?): %s", e)
            return []

        results: list[SearchResult] = []
        for rowid, rank in rows:
            decision = self._fetch_decision(rowid)
            if decision is None:
                continue
            score = 1.0 / (1.0 + abs(rank))
            results.append(SearchResult(decision=decision, score=score, match_type="keyword"))

        return results

    def _fetch_decision(self, decision_id: int) -> Decision | None:
        row = self._conn.execute(
            "SELECT id, content, reasoning, status, source, superseded_by, "
            "created_at, updated_at FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            return None

        scope_rows = self._conn.execute(
            "SELECT id, decision_id, scope_type, scope_value "
            "FROM decision_scopes WHERE decision_id = ?",
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
            scopes=scopes,
        )

    def _has_vec_table(self) -> bool:
        try:
            row = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_embeddings'"
            ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False
