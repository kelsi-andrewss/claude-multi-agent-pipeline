"""Knowledge DB tools: decisions, patterns, and pitfalls migration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from constants import (
    DECISION_STATUSES,
    PATTERN_SEVERITIES,
    PATTERN_STATUSES,
    PITFALLS_CATEGORY_MAP,
    PITFALLS_DIR,
    SCOPE_TYPES,
)
from tools_pm_helpers import _db_op, _next_id

# OpenMemory constants
OM_DB = Path.home() / ".claude" / ".claude" / "openmemory.sqlite"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
OLLAMA_MODEL = "nomic-embed-text"


def _get_embedding(text: str) -> list[float] | None:
    """Call Ollama to embed text. Returns embedding vector or None if unavailable."""
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": text}).encode()
    req = Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("embedding")
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        return None


def _embedding_to_blob(vec: list[float]) -> bytes:
    """Convert embedding vector to binary blob for storage."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _om_shadow_decision(decision_id: str, content: str, user_id: str) -> None:
    """Shadow a decision to OpenMemory for semantic search. Silently fails if OpenMemory unavailable."""
    try:
        if not OM_DB.exists():
            return

        # Get embedding from Ollama
        vec = _get_embedding(content)
        if vec is None:
            return

        # Compute simhash from content
        simhash = hashlib.md5(content.encode()).hexdigest()[:16]

        # Insert into OpenMemory
        conn = sqlite3.connect(str(OM_DB), timeout=10)
        try:
            mem_id = str(uuid.uuid4())
            now_ts = int(time.time())
            tags = json.dumps(["decision", decision_id])
            blob = _embedding_to_blob(vec)

            conn.execute(
                "INSERT OR IGNORE INTO memories "
                "(id, user_id, content, simhash, primary_sector, tags, meta, "
                "mean_dim, mean_vec, created_at, updated_at, last_seen_at, "
                "salience, decay_lambda, feedback_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mem_id, user_id, content, simhash,
                    "semantic", tags, None,
                    len(vec), blob,
                    now_ts, now_ts, now_ts,
                    0.5, 0.01, 0,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # OpenMemory failure must never break the tool
        return


def _migrate_pitfalls(conn) -> dict:
    """Parse pitfalls markdown files and insert as patterns. Returns summary."""
    counts: dict[str, int] = {}
    for filename, category in PITFALLS_CATEGORY_MAP.items():
        filepath = PITFALLS_DIR / filename
        if not filepath.exists():
            continue
        lines = filepath.read_text(encoding="utf-8").splitlines()
        inserted = 0
        for line in lines:
            line = line.strip()
            if not line.startswith("- "):
                continue
            description = line[2:].strip()
            for sep in (" — ", ". ", " – "):
                if sep in description:
                    title = description[:description.index(sep)]
                    break
            else:
                title = description[:80]
            existing = conn.execute(
                "SELECT id FROM patterns WHERE description = ? AND category = ?",
                (description, category),
            ).fetchone()
            if existing:
                continue
            pattern_id = _next_id(conn, "patterns", "pattern-")
            conn.execute(
                """INSERT INTO patterns (id, title, description, category, severity, source)
                   VALUES (?, ?, ?, ?, 'must', ?)""",
                (pattern_id, title, description, category, filename),
            )
            inserted += 1
        counts[category] = inserted
    conn.commit()
    return counts


def register(mcp):
    @mcp.tool()
    async def pm_add_decision(
        title: str,
        chose: str,
        rejected: str | None = None,
        reasoning: str | None = None,
        scopes: list[dict[str, str]] | None = None,
        story_id: str | None = None,
    ) -> str:
        """Record an architectural decision with optional file/tech scopes.

        Args:
            title: Short description of the decision.
            chose: What was chosen.
            rejected: What alternatives were rejected.
            reasoning: Why this choice was made.
            scopes: List of scope dicts with 'type' (file|pattern|tech) and 'value' keys.
            story_id: Optional story ID this decision was made during.
        """
        with _db_op() as conn:
            decision_id = _next_id(conn, "decisions", "decision-")
            conn.execute(
                """INSERT INTO decisions (id, title, chose, rejected, reasoning, story_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (decision_id, title, chose, rejected, reasoning, story_id),
            )
            if scopes:
                for scope in scopes:
                    scope_type = scope.get("type", "")
                    scope_value = scope.get("value", "")
                    if scope_type not in SCOPE_TYPES:
                        conn.rollback()
                        return f"Invalid scope type '{scope_type}'. Valid: {sorted(SCOPE_TYPES)}"
                    conn.execute(
                        """INSERT INTO decision_scopes (decision_id, scope_type, scope_value)
                           VALUES (?, ?, ?)""",
                        (decision_id, scope_type, scope_value),
                    )
            # Shadow decision to OpenMemory for semantic search
            content = f"{title}: chose {chose}. {reasoning or ''}"
            _om_shadow_decision(decision_id, content, "proj:dotclaude")
            result = {
                "id": decision_id,
                "title": title,
                "chose": chose,
                "rejected": rejected,
                "reasoning": reasoning,
                "scopes": scopes or [],
                "story_id": story_id,
            }
            return json.dumps(result)

    @mcp.tool()
    async def pm_list_decisions(
        scope_value: str | None = None,
        scope_type: str | None = None,
        status: str | None = "active",
        story_id: str | None = None,
    ) -> str:
        """List decisions, optionally filtered by scope, status, or story.

        Args:
            scope_value: Filter by scope value (supports LIKE patterns, e.g. 'src/hooks/%').
            scope_type: Filter by scope type (file, pattern, tech).
            status: Filter by status (default: 'active'). Set to None/empty for all.
            story_id: Filter by story ID.
        """
        with _db_op(readonly=True) as conn:
            conditions = []
            params: list[str] = []

            if scope_value:
                conditions.append(
                    """d.id IN (SELECT decision_id FROM decision_scopes
                               WHERE scope_value LIKE ?)"""
                )
                params.append(scope_value)
            if scope_type:
                if scope_type not in SCOPE_TYPES:
                    return f"Invalid scope_type '{scope_type}'. Valid: {sorted(SCOPE_TYPES)}"
                conditions.append(
                    """d.id IN (SELECT decision_id FROM decision_scopes
                               WHERE scope_type = ?)"""
                )
                params.append(scope_type)
            if status:
                if status not in DECISION_STATUSES:
                    return f"Invalid status '{status}'. Valid: {sorted(DECISION_STATUSES)}"
                conditions.append("d.status = ?")
                params.append(status)
            if story_id:
                conditions.append("d.story_id = ?")
                params.append(story_id)

            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            rows = conn.execute(
                f"SELECT * FROM decisions d{where} ORDER BY decided_at DESC", params
            ).fetchall()

            results = []
            for row in rows:
                d = dict(row)
                scope_rows = conn.execute(
                    "SELECT scope_type, scope_value FROM decision_scopes WHERE decision_id = ?",
                    (d["id"],),
                ).fetchall()
                d["scopes"] = [{"type": s["scope_type"], "value": s["scope_value"]} for s in scope_rows]
                results.append(d)

            return json.dumps(results)

    @mcp.tool()
    async def pm_supersede_decision(
        decision_id: str,
        new_decision_id: str,
        reason: str | None = None,
    ) -> str:
        """Mark a decision as superseded by a newer one.

        Args:
            decision_id: The decision being superseded.
            new_decision_id: The decision that replaces it.
            reason: Optional explanation for the change.
        """
        with _db_op() as conn:
            old = conn.execute("SELECT id FROM decisions WHERE id = ?", (decision_id,)).fetchone()
            if not old:
                return f"Decision '{decision_id}' not found."
            new = conn.execute("SELECT id FROM decisions WHERE id = ?", (new_decision_id,)).fetchone()
            if not new:
                return f"New decision '{new_decision_id}' not found."
            conn.execute(
                "UPDATE decisions SET status = 'superseded', superseded_by = ? WHERE id = ?",
                (new_decision_id, decision_id),
            )
            msg = f"Decision '{decision_id}' superseded by '{new_decision_id}'."
            if reason:
                msg += f" Reason: {reason}"
            return msg

    @mcp.tool()
    async def pm_add_pattern(
        title: str,
        description: str,
        category: str,
        severity: str = "must",
        source: str | None = None,
    ) -> str:
        """Add a coding pattern or pitfall to the knowledge DB.

        Args:
            title: Short name for the pattern.
            description: Full description of the pattern or pitfall.
            category: Any tech/domain string (e.g. react, flutter, python, go, architecture, general).
                      New categories are created on first use. Add a refs/pitfalls-<category>.md file
                      for auto-import on server startup.
            severity: One of: must, should, prefer (default: must).
            source: Where this pattern came from (e.g. filename, story ID).
        """
        if severity not in PATTERN_SEVERITIES:
            return f"Invalid severity '{severity}'. Valid: {sorted(PATTERN_SEVERITIES)}"
        with _db_op() as conn:
            pattern_id = _next_id(conn, "patterns", "pattern-")
            conn.execute(
                """INSERT INTO patterns (id, title, description, category, severity, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (pattern_id, title, description, category, severity, source),
            )
            result = {
                "id": pattern_id,
                "title": title,
                "description": description,
                "category": category,
                "severity": severity,
                "source": source,
            }
            return json.dumps(result)

    @mcp.tool()
    async def pm_list_patterns(
        category: str | None = None,
        severity: str | None = None,
        status: str | None = "active",
    ) -> str:
        """List patterns/pitfalls, optionally filtered by category, severity, or status.

        Args:
            category: Filter by category string (e.g. react, flutter, python, go).
                      Any string is accepted — returns empty list if no patterns exist for it.
            severity: Filter by severity (must, should, prefer).
            status: Filter by status (default: 'active'). Set to None/empty for all.
        """
        with _db_op(readonly=True) as conn:
            conditions = []
            params: list[str] = []

            if category:
                conditions.append("category = ?")
                params.append(category)
            if severity:
                if severity not in PATTERN_SEVERITIES:
                    return f"Invalid severity '{severity}'. Valid: {sorted(PATTERN_SEVERITIES)}"
                conditions.append("severity = ?")
                params.append(severity)
            if status:
                if status not in PATTERN_STATUSES:
                    return f"Invalid status '{status}'. Valid: {sorted(PATTERN_STATUSES)}"
                conditions.append("status = ?")
                params.append(status)

            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            rows = conn.execute(
                f"SELECT * FROM patterns{where} ORDER BY category, severity", params
            ).fetchall()

            return json.dumps([dict(r) for r in rows])

    @mcp.tool()
    async def pm_deprecate_pattern(
        pattern_id: str,
        reason: str | None = None,
    ) -> str:
        """Mark a pattern as deprecated.

        Args:
            pattern_id: The pattern to deprecate.
            reason: Optional explanation for deprecation.
        """
        with _db_op() as conn:
            row = conn.execute("SELECT id FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
            if not row:
                return f"Pattern '{pattern_id}' not found."
            conn.execute("UPDATE patterns SET status = 'deprecated' WHERE id = ?", (pattern_id,))
            msg = f"Pattern '{pattern_id}' deprecated."
            if reason:
                msg += f" Reason: {reason}"
            return msg
