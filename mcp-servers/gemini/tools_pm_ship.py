"""PM ship tool: one-shot pipeline that creates epic, groups items, creates stories/tasks, and runs Gemini planning."""

from __future__ import annotations

import json
import time
from pathlib import Path

from constants import MAX_CODE_BYTES, PLAN_SYSTEM_INSTRUCTION
from gemini_client import _discover_files, _gemini, _load_audit_context, _read_files_within_budget
from tools_pm_helpers import (
    _add_task_to_story,
    _apply_plan_to_story,
    _build_plan_prompt,
    _ensure_backlog_epic,
    _get_db,
    _group_items,
    _next_id,
    _story_to_dict,
)

SHIP_GROUPING_INSTRUCTION = (
    "You are a senior engineer breaking down a project into stories and tasks.\n"
    "Given the user's requirements document and feature list, return a JSON object:\n"
    '{"proposed_stories": [{"title": str, "tasks": [str], "write_files": [str], "agent": "architect"|"quick-fixer"}]}\n'
    "Group related items into stories. Each story should be independently implementable.\n"
    "Return ONLY valid JSON."
)


def register(mcp):
    @mcp.tool()
    async def pm_ship(
        items: list[str],
        title: str | None = None,
        context: str | None = None,
        epic_id: str | None = None,
        target_date: str | None = None,
        project_root: str | None = None,
        auto_commit: bool = True,
        proposal_id: str | None = None,
    ) -> str:
        """One-shot pipeline: create epic, group items into stories/tasks, run Gemini planning. Returns structured result for Claude to write plan files and launch coders.

        Args:
            items: Feature descriptions or todo items to plan.
            title: Epic title. Defaults to first item if omitted.
            context: Raw PRD/requirements text. When provided, Gemini groups items intelligently instead of using Jaccard clustering.
            epic_id: Resume mode — skip epic creation, plan unplanned stories in this epic.
            target_date: Optional target date for the epic (ISO format, e.g., '2026-04-01').
            project_root: Absolute path to project root for codebase context.
            auto_commit: If False, store proposal in pending_proposals and return for review. Re-call with proposal_id and auto_commit=True to commit.
            proposal_id: Commit a previously stored proposal. Requires auto_commit=True.
        """
        _root = Path(project_root).resolve() if project_root else None
        conn = _get_db()
        try:
            # --- Resume from pending proposal ---
            if proposal_id and auto_commit:
                row = conn.execute(
                    "SELECT data FROM pending_proposals WHERE id = ?", (proposal_id,)
                ).fetchone()
                if not row:
                    return json.dumps({"error": f"proposal_id '{proposal_id}' not found or already used."})
                proposal = json.loads(row["data"])
                conn.execute("DELETE FROM pending_proposals WHERE id = ?", (proposal_id,))
                return await _commit_and_plan(
                    conn, proposal, _root, context,
                )

            # --- Resume mode: plan unplanned stories in existing epic ---
            if epic_id and not items:
                epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
                if not epic:
                    return json.dumps({"error": f"Epic '{epic_id}' not found."})

                draft_stories = conn.execute(
                    "SELECT * FROM stories WHERE epic_id = ? AND state IN ('draft','ready') AND archived = 0",
                    (epic_id,)
                ).fetchall()
                if not draft_stories:
                    return json.dumps({"error": f"No draft/ready stories found in epic '{epic_id}'."})

                story_list = [_story_to_dict(s) for s in draft_stories]
                return await _plan_stories(conn, epic_id, dict(epic)["title"], story_list, _root, context)

            if not items:
                return json.dumps({"error": "Provide items to plan, or epic_id to resume an existing epic."})

            # --- Step 1: Create epic ---
            if epic_id:
                epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
                if not epic:
                    return json.dumps({"error": f"Epic '{epic_id}' not found."})
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
            if context:
                grouping_prompt = (
                    f"[System: {SHIP_GROUPING_INSTRUCTION}]\n\n"
                    f"## Requirements Document\n\n{context[:8000]}\n\n"
                    f"## Feature List\n\n" + "\n".join(f"- {item}" for item in items)
                )
                raw = await _gemini(grouping_prompt)
                try:
                    grouping = json.loads(raw)
                    proposed_stories = grouping.get("proposed_stories", [])
                except (json.JSONDecodeError, ValueError):
                    proposed_stories = [{"title": item, "tasks": [], "write_files": [], "agent": "architect"} for item in items]
            else:
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
                conn.commit()
                return json.dumps({
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
            return await _commit_and_plan(
                conn,
                {
                    "epic_id": epic_id,
                    "epic_title": epic_title,
                    "proposed_stories": proposed_stories,
                },
                _root,
                context,
            )

        finally:
            conn.close()

    async def _commit_and_plan(conn, proposal: dict, root: Path | None, context: str | None) -> str:
        """Create stories/tasks in DB, then run Gemini planning on them."""
        epic_id = proposal["epic_id"]
        epic_title = proposal.get("epic_title", "")
        proposed_stories = proposal["proposed_stories"]

        # Ensure epic exists
        epic_exists = conn.execute("SELECT id FROM epics WHERE id = ?", (epic_id,)).fetchone()
        if not epic_exists:
            if epic_id == "epic-backlog":
                _ensure_backlog_epic(conn)
            else:
                return json.dumps({"error": f"Epic '{epic_id}' not found."})

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

        conn.commit()

        story_list = []
        for cs in created_stories:
            row = conn.execute("SELECT * FROM stories WHERE id = ?", (cs["id"],)).fetchone()
            if row:
                story_list.append(_story_to_dict(row))

        return await _plan_stories(conn, epic_id, epic_title, story_list, root, context)

    async def _plan_stories(
        conn, epic_id: str, epic_title: str, story_list: list[dict],
        root: Path | None, context: str | None,
    ) -> str:
        """Run Gemini planning on a list of stories and return structured result."""
        audit_context = _load_audit_context(root=root)
        files = _discover_files(None, root=root)
        code_content, _ = _read_files_within_budget(files, MAX_CODE_BYTES, root=root)

        subject_lines = [f"- Story {s['id']}: {s['title']}" for s in story_list]
        subject = (
            f"Epic ID: {epic_id}\n"
            f"Epic title: {epic_title}\n\n"
            "Stories to plan (return a JSON array, one object per story in the same order):\n"
            + "\n".join(subject_lines)
            + "\n\nEach array element must have: story_id, agent, write_files, tasks, parallel_group, depends_on."
        )

        prompt = _build_plan_prompt(subject, audit_context, code_content, user_context=context)
        raw = await _gemini(prompt)

        try:
            plans = json.loads(raw)
            if not isinstance(plans, list):
                plans = [plans]
        except (json.JSONDecodeError, ValueError):
            conn.commit()
            return json.dumps({
                "epic_id": epic_id,
                "epic_title": epic_title,
                "stories": [{"id": s["id"], "title": s["title"]} for s in story_list],
                "warning": "Gemini planning returned malformed JSON. Stories created but not planned.",
                "raw": raw[:2000],
            })

        plans_by_id = {}
        for plan_data in plans:
            pid = plan_data.get("story_id")
            if pid:
                plans_by_id[pid] = plan_data

        story_results = []
        for s in story_list:
            sid = s["id"]
            plan_data = plans_by_id.get(sid)
            if plan_data is None:
                story_results.append({
                    "id": sid,
                    "title": s["title"],
                    "agent": s.get("agent"),
                    "write_files": s.get("write_files", []),
                    "tasks": [],
                    "parallel_group": 1,
                    "depends_on": [],
                    "warning": "No matching plan returned by Gemini.",
                })
                continue

            summary = _apply_plan_to_story(conn, sid, plan_data)
            story_results.append({
                "id": sid,
                "title": s["title"],
                "agent": summary["agent"],
                "write_files": plan_data.get("write_files", []),
                "tasks": plan_data.get("tasks", []),
                "parallel_group": summary["parallel_group"],
                "depends_on": summary["depends_on"],
            })

        conn.commit()

        # Build execution plan from parallel groups
        group_map: dict[int, list[str]] = {}
        for sr in story_results:
            g = sr.get("parallel_group", 1)
            group_map.setdefault(g, []).append(sr["id"])

        execution_plan = {
            "parallel_groups": [
                {"group": g, "stories": sids}
                for g, sids in sorted(group_map.items())
            ]
        }

        return json.dumps({
            "epic_id": epic_id,
            "epic_title": epic_title,
            "stories": story_results,
            "execution_plan": execution_plan,
        })
