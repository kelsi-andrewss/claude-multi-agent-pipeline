"""Standalone MCP server exposing project decision memory tools."""

from __future__ import annotations

import fnmatch
import sys
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

    return f"Recorded decision #{decision_id}: {content}"


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


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
