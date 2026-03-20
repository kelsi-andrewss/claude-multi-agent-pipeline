"""Standalone MCP server exposing project decision memory tools."""

from __future__ import annotations

import fnmatch
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SERVER_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP

from decision_memory.dump import dump_to_sql
from decision_memory.embeddings import EmbeddingProvider
from decision_memory.search import SearchEngine
from decision_memory.store import DecisionStore
from decision_memory.types import Decision, DecisionScope

mcp = FastMCP("decisions")

_store: DecisionStore | None = None
_provider: EmbeddingProvider | None = None


def _detect_project_root() -> Path:
    """Walk up from cwd looking for a .claude/ directory to identify the project root."""
    current = Path.cwd().resolve()
    for directory in [current, *current.parents]:
        if (directory / ".claude").is_dir():
            return directory
    return current


def _get_store() -> DecisionStore:
    global _store
    if _store is None:
        root = _detect_project_root()
        _store = DecisionStore(root)
    _store.ensure_ready()
    return _store


def _get_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        _provider = EmbeddingProvider()
    return _provider


def _format_decision(d: Decision) -> str:
    parts = [f"[{d.id}] {d.content}"]
    if d.reasoning:
        parts.append(f"  Reasoning: {d.reasoning}")
    parts.append(f"  Status: {d.status} | Source: {d.source}")
    if d.scopes:
        scope_strs = [f"{s.scope_type}:{s.scope_value}" for s in d.scopes]
        parts.append(f"  Scopes: {', '.join(scope_strs)}")
    if d.created_at:
        parts.append(f"  Created: {d.created_at}")
    return "\n".join(parts)


def _compute_scope_overlap(new_patterns: set[str], existing_patterns: set[str]) -> float:
    """Return overlap ratio: len(intersection) / max(len(a), len(b)). 0.0 when both empty."""
    if not new_patterns and not existing_patterns:
        return 0.0
    intersection = new_patterns & existing_patterns
    return len(intersection) / max(len(new_patterns), len(existing_patterns))


def _staleness_tier(created_at: str | None) -> str:
    """Return 'fresh' (<7d), 'aging' (7-30d), 'stale' (>30d), or 'unknown'."""
    if not created_at:
        return "unknown"
    try:
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - dt).days
        if days < 7:
            return "fresh"
        if days <= 30:
            return "aging"
        return "stale"
    except (ValueError, TypeError):
        return "unknown"


@mcp.tool()
def record_project_decision(
    content: str,
    reasoning: str | None = None,
    file_patterns: list[str] | None = None,
    status: str = "active",
    source: str = "human",
) -> str:
    """Record a project decision. Persists to SQLite + SQL dump for portability.

    Args:
        content: The decision text.
        reasoning: Why this decision was made.
        file_patterns: File glob patterns this decision applies to (e.g. ["src/*.py", "tests/"]).
        status: One of: active, deprecated, superseded, violated.
        source: One of: human, ai-discovered, ai-proposed.
    """
    store = _get_store()

    scopes = []
    for pattern in file_patterns or []:
        scopes.append(DecisionScope(id=None, decision_id=0, scope_type="file", scope_value=pattern))

    decision = Decision(
        id=None,
        content=content,
        reasoning=reasoning,
        status=status,
        source=source,
        superseded_by=None,
        created_at=None,
        updated_at=None,
        scopes=scopes,
    )

    decision_id = store.record(decision)

    superseded_ids = []
    warnings = []
    new_patterns = {s.scope_value for s in scopes}
    if new_patterns:
        existing = store.list_all(status="active")
        conn = store._get_connection()
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
            conn.commit()
        finally:
            conn.close()

    provider = _get_provider()
    if provider.available():
        conn = store._get_connection()
        try:
            engine = SearchEngine(conn, provider)
            engine.rebuild_index()
            conn.commit()
        finally:
            conn.close()

    dump_to_sql(store, store.dump_path)

    parts = [f"Recorded decision #{decision_id}: {content}"]
    if superseded_ids:
        ids_str = ", ".join(f"#{d}" for d in superseded_ids)
        parts.append(f"Auto-superseded: {ids_str}")
    for w in warnings:
        parts.append(f"Warning: {w}")
    return "\n".join(parts)


@mcp.tool()
def query_project_decisions(
    query_text: str | None = None,
    active_files: list[str] | None = None,
    limit: int = 5,
) -> str:
    """Search project decisions by text query and/or file patterns.

    Args:
        query_text: Natural language search query.
        active_files: File paths to filter decisions by scope.
        limit: Maximum results to return (default 5).
    """
    store = _get_store()

    if query_text:
        provider = _get_provider()
        conn = store._get_connection()
        try:
            engine = SearchEngine(conn, provider)
            results = engine.hybrid_search(query_text, limit=limit)
        finally:
            conn.close()

        if active_files:
            filtered = []
            for r in results:
                if not r.decision.scopes:
                    filtered.append(r)
                    continue
                for scope in r.decision.scopes:
                    if scope.scope_type == "file" and any(
                        fnmatch.fnmatch(f, scope.scope_value) for f in active_files
                    ):
                        filtered.append(r)
                        break
            results = filtered

        if not results:
            return "No decisions found."

        lines = [f"Found {len(results)} decision(s):\n"]
        for r in results:
            lines.append(f"{_format_decision(r.decision)}")
            lines.append(f"  Match: {r.match_type} (score: {r.score:.4f})")
            lines.append("")
        return "\n".join(lines)

    if active_files:
        all_decisions = store.list_all(status="active")
        matched = []
        for d in all_decisions:
            for scope in d.scopes:
                if scope.scope_type == "file" and any(
                    fnmatch.fnmatch(f, scope.scope_value) for f in active_files
                ):
                    matched.append(d)
                    break
        matched = matched[:limit]
        if not matched:
            return "No decisions found for the given files."
        lines = [f"Found {len(matched)} decision(s):\n"]
        for d in matched:
            lines.append(_format_decision(d))
            lines.append("")
        return "\n".join(lines)

    all_decisions = store.list_all(status="active")[:limit]
    if not all_decisions:
        return "No active decisions found."
    lines = [f"Found {len(all_decisions)} active decision(s):\n"]
    for d in all_decisions:
        lines.append(_format_decision(d))
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def sync_decision_store() -> str:
    """Force rebuild the decision database from the SQL dump file.

    Use this after manually editing decisions.sql or pulling changes that
    modified the dump.
    """
    store = _get_store()
    store.sync_from_dump()

    provider = _get_provider()
    if provider.available():
        conn = store._get_connection()
        try:
            engine = SearchEngine(conn, provider)
            count = engine.rebuild_index()
            conn.commit()
        finally:
            conn.close()
        return f"Rebuilt decision store from dump. Re-indexed {count} decision(s)."

    return "Rebuilt decision store from dump. Embedding index skipped (fastembed unavailable)."


@mcp.tool()
def get_decision(decision_id: int) -> str:
    """Look up a single decision by ID. Returns full content, reasoning, scopes, and freshness score (if available).

    Args:
        decision_id: The numeric decision ID.
    """
    store = _get_store()
    d = store.get(decision_id)
    if d is None:
        return f"Decision #{decision_id} not found."

    lines = [_format_decision(d)]
    if d.domain:
        lines.append(f"  Domain: {d.domain}")
    lines.append(f"  Staleness: {_staleness_tier(d.created_at)}")

    run_db = os.path.expanduser("~/.claude/.claude/run-state.db")
    if os.path.exists(run_db):
        rconn = sqlite3.connect(run_db, timeout=5)
        try:
            row = rconn.execute(
                "SELECT staleness_score, days_since_activity, reinforcement_count "
                "FROM decision_freshness WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            if row:
                lines.append(
                    f"  Freshness: score={row[0]:.2f}, "
                    f"days_inactive={row[1]}, reinforcements={row[2]}"
                )
        except sqlite3.OperationalError:
            pass
        finally:
            rconn.close()

    return "\n".join(lines)


@mcp.tool()
def query_decisions_by_domain(domain: str, limit: int = 50) -> str:
    """Query active decisions filtered by domain. Returns matching decisions with staleness tier labels.

    Gracefully returns an empty result if the domain column doesn't exist yet (Phase 3 schema).

    Args:
        domain: Domain name to filter by (exact match or substring).
        limit: Maximum results to return (default 50).
    """
    store = _get_store()
    conn = store._get_connection()
    try:
        columns = conn.execute("PRAGMA table_info(decisions)").fetchall()
        has_domain = any(col[1] == "domain" for col in columns)

        if not has_domain:
            return (
                "No decisions found (domain column not available "
                "-- Phase 3 schema required)."
            )

        rows = conn.execute(
            "SELECT id, content, reasoning, status, source, superseded_by, "
            "created_at, updated_at FROM decisions "
            "WHERE status = 'active' AND (domain = ? OR domain LIKE ?) "
            "ORDER BY id LIMIT ?",
            (domain, f"%{domain}%", limit),
        ).fetchall()

        if not rows:
            return f"No decisions found for domain '{domain}'."

        lines = [f"Found {len(rows)} decision(s) for domain '{domain}':\n"]
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
            d = Decision(
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
            lines.append(_format_decision(d))
            lines.append(f"  Staleness: {_staleness_tier(d.created_at)}")
            lines.append("")

        return "\n".join(lines)
    finally:
        conn.close()


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
