"""PM read/query tools: pm_get_epic, pm_get_story, pm_list_stories, pm_search, pm_view, pm_roadmap, pm_dev_branch."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from constants import AT_RISK_DAYS_THRESHOLD, AT_RISK_PCT_THRESHOLD, EPIC_STATES, STORY_STATES
from format_response import (
    fmt_dev_branch,
    fmt_get_epic,
    fmt_get_story,
    fmt_list_stories,
    fmt_roadmap,
    fmt_search,
    fmt_view,
)
from tools_pm_helpers import (
    _db_op,
    _epic_to_dict,
    _fetch_story_deps,
    _story_to_dict,
)


def register(mcp):
    @mcp.tool()
    async def pm_get_epic(epic_id: str) -> str:
        """Get a single epic with all its active stories and their tasks.

        Args:
            epic_id: The epic ID (e.g., 'epic-022').
        """
        with _db_op(readonly=True) as conn:
            epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
            if not epic:
                return f"Epic '{epic_id}' not found."
            ed = _epic_to_dict(epic)

            stories = conn.execute(
                "SELECT * FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
                (epic_id,)
            ).fetchall()

            story_list = []
            for story in stories:
                sd = _story_to_dict(story)
                tasks = conn.execute(
                    "SELECT * FROM tasks WHERE story_id = ? ORDER BY id",
                    (sd["id"],)
                ).fetchall()
                sd["tasks"] = [dict(t) for t in tasks]
                story_list.append(sd)

            ed["stories"] = story_list
            return fmt_get_epic(ed)

    @mcp.tool()
    async def pm_get_story(story_id: str) -> str:
        """Get a single story with its tasks and reverse dependency info.

        Args:
            story_id: The story ID (e.g., 'story-185').
        """
        with _db_op(readonly=True) as conn:
            story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
            if not story:
                return f"Story '{story_id}' not found."
            sd = _story_to_dict(story)
            sd["depends_on"] = _fetch_story_deps(conn, story_id)

            tasks = conn.execute(
                "SELECT * FROM tasks WHERE story_id = ? ORDER BY id", (story_id,)
            ).fetchall()
            sd["tasks"] = [dict(t) for t in tasks]

            blocked_by_me = conn.execute(
                "SELECT s.id, s.title, s.state FROM stories s "
                "JOIN story_dependencies sd ON s.id = sd.story_id "
                "WHERE sd.depends_on = ? AND s.archived = 0",
                (story_id,)
            ).fetchall()
            if blocked_by_me:
                sd["blocks"] = [{"id": r["id"], "title": r["title"], "state": r["state"]} for r in blocked_by_me]

            return fmt_get_story(sd)

    @mcp.tool()
    async def pm_list_stories(
        epic_id: str | None = None,
        state: str | None = None,
        agent: str | None = None,
        include_archived: bool = False,
    ) -> str:
        """List stories with optional filters. Archived stories excluded by default.

        Args:
            epic_id: Filter by epic ID.
            state: Filter by story state.
            agent: Filter by agent type ('quick-fixer', 'architect', etc.).
            include_archived: If true, include archived stories (default false).
        """
        with _db_op(readonly=True) as conn:
            conditions = []
            params: list = []

            if not include_archived:
                conditions.append("archived = 0")

            if epic_id:
                conditions.append("epic_id = ?")
                params.append(epic_id)

            if state:
                if state not in STORY_STATES:
                    return f"Invalid state '{state}'. Valid: {sorted(STORY_STATES)}"
                conditions.append("state = ?")
                params.append(state)

            if agent:
                conditions.append("agent = ?")
                params.append(agent)

            where = " AND ".join(conditions) if conditions else "1=1"
            stories = conn.execute(
                f"SELECT * FROM stories WHERE {where} ORDER BY COALESCE(order_idx, 2147483647), id", params
            ).fetchall()

            return fmt_list_stories([_story_to_dict(s) for s in stories])

    @mcp.tool()
    async def pm_search(query: str, scope: str | None = None) -> str:
        """Search across epics, stories, and tasks by title or ID substring.

        Args:
            query: Search term (matched as substring against titles and IDs).
            scope: Limit search to 'epics', 'stories', or 'tasks'. Omit to search all.
        """
        with _db_op(readonly=True) as conn:
            results = []
            pattern = f"%{query}%"

            if scope in (None, "epics"):
                epics = conn.execute(
                    "SELECT * FROM epics WHERE id LIKE ? OR title LIKE ?",
                    (pattern, pattern)
                ).fetchall()
                for e in epics:
                    results.append({"type": "epic", **_epic_to_dict(e)})

            if scope in (None, "stories"):
                stories = conn.execute(
                    "SELECT * FROM stories WHERE (id LIKE ? OR title LIKE ?) AND archived = 0",
                    (pattern, pattern)
                ).fetchall()
                for s in stories:
                    results.append({"type": "story", **_story_to_dict(s)})

            if scope in (None, "tasks"):
                tasks = conn.execute(
                    "SELECT t.*, s.title as story_title FROM tasks t "
                    "JOIN stories s ON t.story_id = s.id "
                    "WHERE t.id LIKE ? OR t.title LIKE ?",
                    (pattern, pattern)
                ).fetchall()
                for t in tasks:
                    results.append({"type": "task", **dict(t)})

            return fmt_search(results)

    @mcp.tool()
    async def pm_view(
        epic_id: str | None = None,
        detail: str = "board",
        include_archived: bool = False,
    ) -> str:
        """Combined dashboard view with configurable detail level.

        Args:
            epic_id: Scope to a single epic. Omit for all active epics.
            detail: Detail level — 'summary' (epic list + story counts), 'board' (kanban + WIP + callouts), or 'full' (board + tasks + cycle time). Default: 'board'.
            include_archived: Include archived story counts in epic progress summaries.
        """
        valid_details = {"summary", "board", "full"}
        if detail not in valid_details:
            return f"Invalid detail '{detail}'. Valid: {sorted(valid_details)}"

        with _db_op(readonly=True) as conn:
            if epic_id:
                epic_rows = conn.execute(
                    "SELECT * FROM epics WHERE id = ?", (epic_id,)
                ).fetchall()
                if not epic_rows:
                    return fmt_view({"error": f"Epic '{epic_id}' not found."})
            else:
                epic_rows = conn.execute(
                    "SELECT * FROM epics WHERE state = 'active'"
                ).fetchall()

            epics_out = []
            for epic in epic_rows:
                ed = _epic_to_dict(epic)
                archived_filter = "" if include_archived else " AND archived = 0"
                counts = conn.execute(
                    f"SELECT state, COUNT(*) as cnt FROM stories "
                    f"WHERE epic_id = ?{archived_filter} GROUP BY state",
                    (ed["id"],)
                ).fetchall()
                by_state = {r["state"]: r["cnt"] for r in counts}
                total = sum(by_state.values())
                done_count = by_state.get("done", 0) + by_state.get("shipped", 0)
                pct_done = round(done_count / total * 100) if total else 0
                epic_entry = {
                    "id": ed["id"],
                    "title": ed["title"],
                    "state": ed["state"],
                    "persistent": ed.get("persistent", False),
                    "progress": {
                        "total": total,
                        "by_state": by_state,
                        "pct_done": pct_done,
                    },
                }
                if ed.get("milestone_order") is not None:
                    epic_entry["milestone_order"] = ed["milestone_order"]
                if ed.get("target_date"):
                    epic_entry["target_date"] = ed["target_date"]
                epics_out.append(epic_entry)

            if detail == "summary":
                return fmt_view({
                    "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                    "scope": epic_id or "all",
                    "epics": epics_out,
                })

            # board and full both include kanban + WIP + callouts
            epic_filter = ""
            story_params: list = []
            if epic_id:
                epic_filter = " AND epic_id = ?"
                story_params.append(epic_id)

            stories = conn.execute(
                f"SELECT * FROM stories WHERE archived = 0{epic_filter} "
                f"ORDER BY COALESCE(order_idx, 2147483647), id",
                story_params
            ).fetchall()

            board: dict[str, list] = {}
            for story in stories:
                sd = _story_to_dict(story)
                state = sd["state"]
                if state not in board:
                    board[state] = []
                entry = {
                    "id": sd["id"],
                    "title": sd["title"],
                    "epic_id": sd["epic_id"],
                    "agent": sd.get("agent"),
                    "branch": sd.get("branch"),
                }
                if detail == "full":
                    tasks = conn.execute(
                        "SELECT * FROM tasks WHERE story_id = ? ORDER BY id",
                        (sd["id"],)
                    ).fetchall()
                    entry["tasks"] = [dict(t) for t in tasks]
                board[state].append(entry)

            by_state_rows = conn.execute(
                f"SELECT state, COUNT(*) as cnt FROM stories WHERE archived = 0{epic_filter} "
                f"GROUP BY state ORDER BY cnt DESC",
                story_params
            ).fetchall()
            by_agent_rows = conn.execute(
                f"SELECT COALESCE(agent, 'unassigned') as agent, COUNT(*) as cnt "
                f"FROM stories WHERE archived = 0{epic_filter} GROUP BY agent ORDER BY cnt DESC",
                story_params
            ).fetchall()
            wip = {
                "total_active": sum(r["cnt"] for r in by_state_rows),
                "by_state": {r["state"]: r["cnt"] for r in by_state_rows},
                "by_agent": {r["agent"]: r["cnt"] for r in by_agent_rows},
            }

            blocked_rows = conn.execute(
                f"SELECT id, title, epic_id FROM stories "
                f"WHERE state = 'blocked' AND archived = 0{epic_filter}",
                story_params
            ).fetchall()

            stale_cutoff = (datetime.utcnow() - timedelta(days=14)).isoformat()
            stale_rows = conn.execute(
                f"SELECT id, title, epic_id, started_at FROM stories "
                f"WHERE state = 'in-progress' AND archived = 0 "
                f"AND started_at IS NOT NULL AND started_at < ?{epic_filter}",
                [stale_cutoff] + story_params
            ).fetchall()

            callouts = {
                "blocked": [
                    {"id": r["id"], "title": r["title"], "epic_id": r["epic_id"]}
                    for r in blocked_rows
                ],
                "stale": [
                    {"id": r["id"], "title": r["title"], "epic_id": r["epic_id"],
                     "started_at": r["started_at"]}
                    for r in stale_rows
                ],
            }

            result = {
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                "scope": epic_id or "all",
                "epics": epics_out,
                "board": board,
                "wip": wip,
                "callouts": callouts,
            }

            if detail == "full":
                completed = conn.execute(
                    f"SELECT started_at, completed_at FROM stories "
                    f"WHERE archived = 1 AND started_at IS NOT NULL AND completed_at IS NOT NULL{epic_filter}",
                    story_params
                ).fetchall()
                total_hours = 0.0
                count = 0
                for row in completed:
                    try:
                        s = datetime.fromisoformat(row["started_at"])
                        c = datetime.fromisoformat(row["completed_at"])
                        total_hours += (c - s).total_seconds() / 3600
                        count += 1
                    except (ValueError, TypeError):
                        pass
                result["avg_cycle_hours"] = round(total_hours / count, 1) if count else 0

            return fmt_view(result)

    @mcp.tool()
    async def pm_roadmap(
        state: str | None = None,
        include_done: bool = False,
    ) -> str:
        """Bird's-eye roadmap: milestones ordered by priority, progress bars, at-risk detection.

        Args:
            state: Filter epics by state ('active', 'done', 'shipped'). Default: active only.
            include_done: If true, include done/shipped epics in the output.
        """
        with _db_op(readonly=True) as conn:
            if state:
                if state not in EPIC_STATES:
                    return f"Invalid state '{state}'. Valid: {sorted(EPIC_STATES)}"
                epic_rows = conn.execute(
                    "SELECT * FROM epics WHERE state = ? ORDER BY COALESCE(milestone_order, 2147483647), id",
                    (state,)
                ).fetchall()
            elif include_done:
                epic_rows = conn.execute(
                    "SELECT * FROM epics ORDER BY COALESCE(milestone_order, 2147483647), id"
                ).fetchall()
            else:
                epic_rows = conn.execute(
                    "SELECT * FROM epics WHERE state = 'active' ORDER BY COALESCE(milestone_order, 2147483647), id"
                ).fetchall()

            now = datetime.utcnow()
            milestones = []
            unordered = []
            total_epics = 0
            on_track = 0
            at_risk = 0
            completed = 0

            for epic in epic_rows:
                ed = _epic_to_dict(epic)
                total_epics += 1

                counts = conn.execute(
                    "SELECT state, COUNT(*) as cnt FROM stories "
                    "WHERE epic_id = ? AND archived = 0 GROUP BY state",
                    (ed["id"],)
                ).fetchall()
                by_state = {r["state"]: r["cnt"] for r in counts}
                total_stories = sum(by_state.values())
                done_count = by_state.get("done", 0) + by_state.get("shipped", 0)
                pct = round(done_count / total_stories * 100) if total_stories else 0

                blocked_count = conn.execute(
                    "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND state = 'blocked' AND archived = 0",
                    (ed["id"],)
                ).fetchone()[0]

                entry = {
                    "epic_id": ed["id"],
                    "title": ed["title"],
                    "milestone_order": ed.get("milestone_order"),
                    "target_date": ed.get("target_date"),
                    "description": ed.get("description"),
                    "state": ed["state"],
                    "persistent": ed.get("persistent", False),
                    "progress": {"total": total_stories, "done": done_count, "pct": pct},
                    "blocked_count": blocked_count,
                }

                # At-risk detection
                is_at_risk = False
                if ed["state"] == "active" and ed.get("target_date"):
                    try:
                        target = datetime.fromisoformat(ed["target_date"])
                        days_left = (target - now).days
                        if days_left < 0:
                            is_at_risk = True
                        elif days_left <= AT_RISK_DAYS_THRESHOLD and pct < AT_RISK_PCT_THRESHOLD:
                            is_at_risk = True
                    except (ValueError, TypeError):
                        pass
                entry["at_risk"] = is_at_risk

                if ed["state"] in ("done", "shipped"):
                    completed += 1
                elif is_at_risk:
                    at_risk += 1
                else:
                    on_track += 1

                if ed.get("milestone_order") is not None:
                    milestones.append(entry)
                else:
                    unordered.append(entry)

            return fmt_roadmap({
                "milestones": milestones,
                "unordered": unordered,
                "summary": {
                    "total_epics": total_epics,
                    "on_track": on_track,
                    "at_risk": at_risk,
                    "completed": completed,
                },
            })

    @mcp.tool()
    async def pm_dev_branch(epic_id: str) -> str:
        """Returns the dev branch name (always `dev`) and the epic slug for story branch naming.

        Args:
            epic_id: The epic ID (e.g., 'epic-022').
        """
        if epic_id == "epic-backlog":
            return fmt_dev_branch({"dev_branch": "dev", "epic_slug": "backlog"})

        with _db_op(readonly=True) as conn:
            epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
            if not epic:
                return fmt_dev_branch({"error": f"Epic '{epic_id}' not found."})
            title = epic["title"]
            slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40]
            if not slug:
                slug = epic_id
            return fmt_dev_branch({"dev_branch": "dev", "epic_title": title, "epic_slug": slug})
