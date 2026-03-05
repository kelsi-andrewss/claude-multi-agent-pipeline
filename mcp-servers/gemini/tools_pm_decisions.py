"""PM decision preference tools: pm_record_decision, pm_list_decisions_by_type."""

from __future__ import annotations

import json
import time
import uuid

from tools_pm_helpers import _db_op, _get_db


def _ensure_decisions_table(conn):
    """Create the decision_preferences table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decision_preferences (
            id TEXT PRIMARY KEY,
            decision_type TEXT NOT NULL,
            context TEXT NOT NULL,
            chosen_path TEXT NOT NULL,
            alternatives TEXT,
            session_id TEXT,
            confidence REAL DEFAULT 0.5,
            signal_score REAL DEFAULT 0,
            signal_count INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dp_type ON decision_preferences(decision_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dp_created ON decision_preferences(created_at)"
    )


_table_ensured = False


def _ensure_table_once(conn):
    global _table_ensured
    if not _table_ensured:
        _ensure_decisions_table(conn)
        _table_ensured = True


def register(mcp):
    @mcp.tool()
    async def pm_record_decision(
        decision_type: str,
        context: str,
        chosen_path: str,
        alternatives: list[str] | None = None,
        confidence: float | None = None,
        session_id: str | None = None,
    ) -> str:
        """Record a decision preference for later modeling and correlation.

        Tracks decisions made during sessions so that corrections/approvals
        can be correlated with specific decision types.

        Args:
            decision_type: Category of decision (routing, scope, communication, architecture).
            context: What prompted this decision.
            chosen_path: What was decided.
            alternatives: Other options that were considered.
            confidence: Confidence level 0-1 (default 0.5).
            session_id: Optional session identifier for grouping.
        """
        valid_types = ("routing", "scope", "communication", "architecture")
        if decision_type not in valid_types:
            return f"Invalid decision_type '{decision_type}'. Valid: {sorted(valid_types)}"

        now = int(time.time())
        decision_id = f"dp-{uuid.uuid4().hex[:12]}"

        with _db_op() as conn:
            _ensure_table_once(conn)
            conn.execute(
                """INSERT INTO decision_preferences
                   (id, decision_type, context, chosen_path, alternatives, session_id, confidence, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision_id,
                    decision_type,
                    context,
                    chosen_path,
                    json.dumps(alternatives) if alternatives else None,
                    session_id,
                    confidence if confidence is not None else 0.5,
                    now,
                    now,
                ),
            )
            return f"Recorded decision {decision_id} (type={decision_type})"

    @mcp.tool()
    async def pm_list_decisions_by_type(
        decision_type: str | None = None,
        limit: int = 20,
    ) -> str:
        """List recent decision preferences, optionally filtered by type.

        Args:
            decision_type: Filter by category (routing, scope, communication, architecture). Omit for all.
            limit: Max results to return (default 20).
        """
        with _db_op(readonly=True) as conn:
            _ensure_table_once(conn)

            if decision_type:
                valid_types = ("routing", "scope", "communication", "architecture")
                if decision_type not in valid_types:
                    return f"Invalid decision_type '{decision_type}'. Valid: {sorted(valid_types)}"
                rows = conn.execute(
                    "SELECT * FROM decision_preferences WHERE decision_type = ? ORDER BY created_at DESC LIMIT ?",
                    (decision_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM decision_preferences ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            if not rows:
                msg = f"No decision preferences found"
                if decision_type:
                    msg += f" for type '{decision_type}'"
                return msg + "."

            results = []
            for r in rows:
                d = dict(r)
                if d.get("alternatives"):
                    d["alternatives"] = json.loads(d["alternatives"])
                results.append(d)

            lines = [f"Found {len(results)} decision(s):"]
            for d in results:
                alts = d.get("alternatives") or []
                alt_str = f" (alternatives: {', '.join(alts)})" if alts else ""
                sig = f" [signal: {d['signal_score']:+.1f} from {d['signal_count']} events]" if d["signal_count"] else ""
                lines.append(
                    f"  {d['id']} [{d['decision_type']}] conf={d['confidence']:.1f}{sig}"
                    f"\n    context: {d['context']}"
                    f"\n    chose: {d['chosen_path']}{alt_str}"
                )
            return "\n".join(lines)
