"""PM ship tool: creates epic, groups items into stories/tasks in DB. Gemini planning is handled separately by pm_plan_stories."""

from __future__ import annotations

import json
import time

from format_response import fmt_ship
from tools_pm_helpers import (
    _add_task_to_story,
    _db_op,
    _ensure_backlog_epic,
    _group_items,
    _next_id,
    _story_to_dict,
)

def register(mcp):
    @mcp.tool()
    def pm_ship(
        items: list[str],
        title: str | None = None,
        context: str | None = None,
        epic_id: str | None = None,
        target_date: str | None = None,
        project_root: str | None = None,
        auto_commit: bool = True,
        proposal_id: str | None = None,
    ) -> str:
        """Create epic and group items into stories/tasks in the DB. Does NOT run Gemini planning — call pm_plan_stories separately for that.

        Args:
            items: Feature descriptions or todo items to plan.
            title: Epic title. Defaults to first item if omitted.
            context: Raw PRD/requirements text. Stored as the epic description when provided.
            epic_id: Resume mode — skip epic creation, return draft stories in this epic.
            target_date: Optional target date for the epic (ISO format, e.g., '2026-04-01').
            project_root: Absolute path to project root for codebase context.
            auto_commit: If False, store proposal in pending_proposals and return for review. Re-call with proposal_id and auto_commit=True to commit.
            proposal_id: Commit a previously stored proposal. Requires auto_commit=True.
        """
        with _db_op() as conn:
            # --- Resume from pending proposal ---
            if proposal_id and auto_commit:
                row = conn.execute(
                    "SELECT data FROM pending_proposals WHERE id = ?", (proposal_id,)
                ).fetchone()
                if not row:
                    return fmt_ship({"error": f"proposal_id '{proposal_id}' not found or already used."})
                proposal = json.loads(row["data"])
                conn.execute("DELETE FROM pending_proposals WHERE id = ?", (proposal_id,))
                return _commit_stories(conn, proposal)

            # --- Resume mode: plan unplanned stories in existing epic ---
            if epic_id and not items:
                epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
                if not epic:
                    return fmt_ship({"error": f"Epic '{epic_id}' not found."})

                draft_stories = conn.execute(
                    "SELECT * FROM stories WHERE epic_id = ? AND state IN ('draft','ready') AND archived = 0",
                    (epic_id,)
                ).fetchall()
                if not draft_stories:
                    return fmt_ship({"error": f"No draft/ready stories found in epic '{epic_id}'."})

                story_list = [_story_to_dict(s) for s in draft_stories]
                return fmt_ship({
                    "epic_id": epic_id,
                    "epic_title": dict(epic)["title"],
                    "stories": [
                        {"id": s["id"], "title": s["title"], "agent": s.get("agent"), "write_files": s.get("write_files", [])}
                        for s in story_list
                    ],
                })

            if not items:
                return fmt_ship({"error": "Provide items to plan, or epic_id to resume an existing epic."})

            # --- Step 1: Create epic ---
            if epic_id:
                epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
                if not epic:
                    return fmt_ship({"error": f"Epic '{epic_id}' not found."})
                epic_title = dict(epic)["title"]
            else:
                epic_title = title or items[0]
                max_order = conn.execute(
                    "SELECT MAX(milestone_order) FROM epics"
                ).fetchone()[0]
                milestone_order = (max_order or 0) + 1

                epic_id = _next_id(conn, "epics", "epic-")
                description = context[:2000] if context else "\n".join(f"- {i}" for i in items)
                conn.execute(
                    "INSERT INTO epics (id, title, branch, persistent, state, milestone_order, target_date, description) "
                    "VALUES (?, ?, NULL, 0, 'active', ?, ?, ?)",
                    (epic_id, epic_title, milestone_order, target_date, description)
                )

            # --- Step 2: Group items into stories ---
            open_stories = conn.execute(
                "SELECT id, title FROM stories WHERE state NOT IN ('done', 'shipped', 'archived')"
            ).fetchall()
            existing = [{"id": r["id"], "title": r["title"]} for r in open_stories]
            grouped = _group_items(items, existing)
            proposed_stories = grouped["proposed_stories"]

            # --- Step 3: Maybe defer (auto_commit=False) ---
            if not auto_commit:
                proposal = {
                    "epic_id": epic_id,
                    "epic_title": epic_title,
                    "proposed_stories": proposed_stories,
                    "target_date": target_date,
                }
                pid = f"prop-{int(time.time())}"
                conn.execute(
                    "INSERT INTO pending_proposals (id, data) VALUES (?, ?)",
                    (pid, json.dumps(proposal))
                )
                return fmt_ship({
                    "phase": "proposal",
                    "proposal_id": pid,
                    "epic_id": epic_id,
                    "epic_title": epic_title,
                    "story_count": len(proposed_stories),
                    "proposed_stories": [
                        {"title": s["title"], "tasks": s.get("tasks", []), "agent": s.get("agent")}
                        for s in proposed_stories
                    ],
                })

            # --- Step 3b: Commit stories/tasks ---
            return _commit_stories(
                conn,
                {
                    "epic_id": epic_id,
                    "epic_title": epic_title,
                    "proposed_stories": proposed_stories,
                },
            )

    def _commit_stories(conn, proposal: dict) -> str:
        """Create stories/tasks in DB and return the created story list. No Gemini calls."""
        epic_id = proposal["epic_id"]
        epic_title = proposal.get("epic_title", "")
        proposed_stories = proposal["proposed_stories"]

        epic_exists = conn.execute("SELECT id FROM epics WHERE id = ?", (epic_id,)).fetchone()
        if not epic_exists:
            if epic_id == "epic-backlog":
                _ensure_backlog_epic(conn)
            else:
                return fmt_ship({"error": f"Epic '{epic_id}' not found."})

        created_stories = []
        for s in proposed_stories:
            sid = _next_id(conn, "stories", "story-")
            conn.execute(
                """INSERT INTO stories (id, epic_id, title, state, write_files, agent, model,
                   depends_on, needs_testing, needs_review)
                   VALUES (?, ?, ?, 'draft', ?, ?, NULL, '[]', 0, 0)""",
                (
                    sid, epic_id, s["title"],
                    json.dumps(s.get("write_files") or []),
                    s.get("agent"),
                )
            )
            for task_title in s.get("tasks", []):
                _add_task_to_story(conn, sid, task_title)
            created_stories.append({
                "id": sid,
                "title": s["title"],
                "agent": s.get("agent"),
                "write_files": s.get("write_files", []),
                "tasks": s.get("tasks", []),
            })

        return fmt_ship({
            "epic_id": epic_id,
            "epic_title": epic_title,
            "stories": created_stories,
        })
