"""PM analytics tools: pm_cycle_time, pm_throughput, pm_wip."""

from __future__ import annotations

import json
from datetime import datetime

from format_response import fmt_cycle_time, fmt_throughput, fmt_wip
from tools_pm_helpers import _db_op


def register(mcp):
    @mcp.tool()
    async def pm_cycle_time(
        epic_id: str | None = None,
        since: str | None = None,
    ) -> str:
        """Show cycle time for completed stories (time from in-progress to done).

        Args:
            epic_id: Optional epic ID filter.
            since: ISO date string to filter stories completed after this date.
        """
        with _db_op(readonly=True) as conn:
            conditions = ["archived = 1", "started_at IS NOT NULL", "completed_at IS NOT NULL"]
            params: list = []

            if epic_id:
                conditions.append("epic_id = ?")
                params.append(epic_id)
            if since:
                conditions.append("completed_at >= ?")
                params.append(since)

            where = " AND ".join(conditions)
            stories = conn.execute(
                f"SELECT id, title, started_at, completed_at FROM stories WHERE {where} ORDER BY completed_at DESC",
                params
            ).fetchall()

            items = []
            total_hours = 0.0
            for s in stories:
                try:
                    started = datetime.fromisoformat(s["started_at"])
                    completed = datetime.fromisoformat(s["completed_at"])
                    hours = (completed - started).total_seconds() / 3600
                    items.append({
                        "id": s["id"], "title": s["title"],
                        "started_at": s["started_at"], "completed_at": s["completed_at"],
                        "cycle_hours": round(hours, 1),
                    })
                    total_hours += hours
                except (ValueError, TypeError):
                    items.append({
                        "id": s["id"], "title": s["title"],
                        "started_at": s["started_at"], "completed_at": s["completed_at"],
                        "cycle_hours": "N/A",
                    })

            avg_hours = round(total_hours / len(items), 1) if items else 0
            return fmt_cycle_time({
                "metric": "cycle_time",
                "stories": items,
                "count": len(items),
                "average_cycle_hours": avg_hours,
            })

    @mcp.tool()
    async def pm_throughput(
        period: str = "week",
        lookback: int = 4,
        epic_id: str | None = None,
    ) -> str:
        """Show completed story throughput over time.

        Args:
            period: Grouping period — 'day', 'week', or 'month' (default: 'week').
            lookback: Number of periods to look back (default: 4).
            epic_id: Optional epic ID to scope throughput.
        """
        if period == "day":
            group_expr = "DATE(completed_at)"
        elif period == "week":
            group_expr = "strftime('%Y-W%W', completed_at)"
        elif period == "month":
            group_expr = "strftime('%Y-%m', completed_at)"
        else:
            return f"Invalid period '{period}'. Valid: day, week, month."

        with _db_op(readonly=True) as conn:
            tp_filter = ""
            tp_params: list = []
            if epic_id:
                tp_filter = " AND epic_id = ?"
                tp_params.append(epic_id)

            rows = conn.execute(
                f"""SELECT {group_expr} as period, COUNT(*) as completed
                    FROM stories
                    WHERE archived = 1 AND completed_at IS NOT NULL{tp_filter}
                    GROUP BY {group_expr}
                    ORDER BY period DESC
                    LIMIT ?""",
                tp_params + [lookback]
            ).fetchall()

            items = [{"period": r["period"], "completed": r["completed"]} for r in rows]
            total = sum(r["completed"] for r in rows)
            avg = round(total / len(items), 1) if items else 0

            return fmt_throughput({
                "metric": "throughput",
                "period_type": period,
                "data": items,
                "total": total,
                "average_per_period": avg,
            })

    @mcp.tool()
    async def pm_wip(epic_id: str | None = None) -> str:
        """Show work-in-progress: story counts by state, blocked items, and agent distribution.

        Args:
            epic_id: Optional epic ID to scope WIP to a single epic.
        """
        with _db_op(readonly=True) as conn:
            epic_filter = ""
            params: list = []
            if epic_id:
                epic_filter = " AND epic_id = ?"
                params.append(epic_id)

            by_state = conn.execute(
                f"SELECT state, COUNT(*) as cnt FROM stories WHERE archived = 0{epic_filter} GROUP BY state ORDER BY cnt DESC",
                params
            ).fetchall()

            by_agent = conn.execute(
                f"SELECT COALESCE(agent, 'unassigned') as agent, COUNT(*) as cnt FROM stories WHERE archived = 0{epic_filter} GROUP BY agent ORDER BY cnt DESC",
                params
            ).fetchall()

            blocked = conn.execute(
                f"SELECT id, title, epic_id FROM stories WHERE state = 'blocked' AND archived = 0{epic_filter}",
                params
            ).fetchall()

            # Cycle time avg
            ct_conditions = ["archived = 1", "started_at IS NOT NULL", "completed_at IS NOT NULL"]
            ct_params: list = []
            if epic_id:
                ct_conditions.append("epic_id = ?")
                ct_params.append(epic_id)
            ct_where = " AND ".join(ct_conditions)
            ct_stories = conn.execute(
                f"SELECT started_at, completed_at FROM stories WHERE {ct_where}",
                ct_params
            ).fetchall()
            total_hours = 0.0
            ct_count = 0
            for s in ct_stories:
                try:
                    started = datetime.fromisoformat(s["started_at"])
                    completed = datetime.fromisoformat(s["completed_at"])
                    total_hours += (completed - started).total_seconds() / 3600
                    ct_count += 1
                except (ValueError, TypeError):
                    pass
            avg_cycle = round(total_hours / ct_count, 1) if ct_count else 0

            # Throughput (last 4 weeks)
            tp_filter = ""
            tp_params: list = []
            if epic_id:
                tp_filter = " AND epic_id = ?"
                tp_params.append(epic_id)
            tp_rows = conn.execute(
                f"""SELECT strftime('%Y-W%W', completed_at) as period, COUNT(*) as completed
                    FROM stories
                    WHERE archived = 1 AND completed_at IS NOT NULL{tp_filter}
                    GROUP BY period
                    ORDER BY period DESC
                    LIMIT 4""",
                tp_params
            ).fetchall()
            tp_data = [{"period": r["period"], "completed": r["completed"]} for r in tp_rows]
            tp_total = sum(r["completed"] for r in tp_rows)
            tp_avg = round(tp_total / len(tp_data), 1) if tp_data else 0

            # Trend detection
            trend = "stable"
            if len(tp_data) >= 2:
                recent = tp_data[0]["completed"]
                older = tp_data[-1]["completed"]
                if recent > older * 1.3:
                    trend = "improving"
                elif recent < older * 0.7:
                    trend = "declining"

            return fmt_wip({
                "metric": "health",
                "wip": {
                    "total_active": sum(r["cnt"] for r in by_state),
                    "by_state": {r["state"]: r["cnt"] for r in by_state},
                    "by_agent": {r["agent"]: r["cnt"] for r in by_agent},
                },
                "blocked": [{"id": r["id"], "title": r["title"], "epic_id": r["epic_id"]} for r in blocked],
                "cycle_time": {
                    "average_hours": avg_cycle,
                    "sample_size": ct_count,
                },
                "throughput": {
                    "data": tp_data,
                    "average_per_week": tp_avg,
                    "trend": trend,
                },
            })
