"""PM write tools: pm_create_epic, pm_create_story, pm_add_task, pm_plan_items, pm_update_story, pm_update_epic, pm_update_task."""

from __future__ import annotations

import json
import time
from datetime import datetime

from constants import (
    EPIC_STATES,
    STORY_STATES,
    TASK_STATES,
    TERMINAL_STATES,
    VALID_EPIC_TRANSITIONS,
    VALID_STORY_TRANSITIONS,
)
from format_response import (
    fmt_add_task,
    fmt_create_epic,
    fmt_create_story,
    fmt_plan_items,
    fmt_update_epic,
    fmt_update_story,
    fmt_update_task,
)
from tools_pm_helpers import (
    _add_task_to_story,
    _db_op,
    _ensure_backlog_epic,
    _epic_to_dict,
    _group_items,
    _next_id,
    _score_stories_by_similarity,
    _set_story_deps,
    _story_to_dict,
    _validate_dependencies,
    _validate_transition,
)


def _find_best_story_match(conn, title: str) -> tuple[str | None, list[dict]]:
    """Find the best matching open story for a task title."""
    open_stories = conn.execute(
        "SELECT id, title, write_files FROM stories WHERE state NOT IN ('done', 'shipped', 'archived')"
    ).fetchall()

    matches = _score_stories_by_similarity(title, open_stories)

    if not matches:
        return None, []
    if len(matches) == 1:
        return matches[0][1], []
    candidates = [{"story_id": m[1], "title": m[2], "score": round(m[0], 2)} for m in matches[:5]]
    return None, candidates


def _create_story_for_task(conn, title: str, write_files: list[str] | None) -> str:
    """Create a new draft story (in epic-backlog) and return its ID."""
    _ensure_backlog_epic(conn)
    story_id = _next_id(conn, "stories", "story-")
    conn.execute(
        """INSERT INTO stories (id, epic_id, title, state, write_files, agent, model,
           depends_on, needs_testing, needs_review)
           VALUES (?, 'epic-backlog', ?, 'draft', ?, NULL, NULL, '[]', 0, 0)""",
        (story_id, title, json.dumps(write_files or []))
    )
    return story_id


def register(mcp):
    @mcp.tool()
    async def pm_create_epic(
        title: str,
        branch: str | None = None,
        persistent: bool = False,
        milestone_order: int | None = None,
        target_date: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create a new epic with an auto-generated ID.

        Args:
            title: Epic title.
            branch: Optional git branch name (e.g., 'epic/023').
            persistent: If true, epic stays active even when all stories are done.
            milestone_order: Optional integer for roadmap ordering (lower = higher priority).
            target_date: Optional target completion date (ISO format, e.g., '2026-03-15').
            description: Optional epic description.
        """
        with _db_op() as conn:
            if milestone_order is None:
                max_order = conn.execute(
                    "SELECT MAX(milestone_order) FROM epics"
                ).fetchone()[0]
                milestone_order = (max_order or 0) + 1

            epic_id = _next_id(conn, "epics", "epic-")
            conn.execute(
                "INSERT INTO epics (id, title, branch, persistent, state, milestone_order, target_date, description) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
                (epic_id, title, branch, int(persistent), milestone_order, target_date, description)
            )
            return fmt_create_epic({
                "id": epic_id, "title": title, "branch": branch, "persistent": persistent,
                "state": "active", "milestone_order": milestone_order, "target_date": target_date,
                "description": description,
                "suggestions": ["Call pm_plan_items with your story titles to auto-group them into stories and tasks"],
            })

    @mcp.tool()
    async def pm_create_story(
        title: str,
        epic_id: str | None = None,
        write_files: list[str] | None = None,
        test_files: list[str] | None = None,
        agent: str | None = None,
        model: str | None = None,
        depends_on: list[str] | None = None,
        needs_testing: bool = False,
        needs_review: bool = False,
        tasks: list[str] | None = None,
    ) -> str:
        """Create a new story with an auto-generated ID. Defaults to 'backlog' epic if none specified.

        Args:
            title: Story title.
            epic_id: Epic to add the story to. Creates 'epic-backlog' if omitted.
            write_files: List of files this story will modify.
            test_files: List of test files for parallel test agent execution.
            agent: Agent type ('quick-fixer', 'architect', 'manual').
            model: Model to use ('haiku', 'sonnet', 'opus').
            depends_on: List of story IDs this story depends on.
            needs_testing: Whether the story needs testing before merge.
            needs_review: Whether the story needs review before merge.
            tasks: Optional list of task titles to create immediately under this story.
        """
        with _db_op() as conn:
            target_epic = epic_id or "epic-backlog"

            existing = conn.execute("SELECT id FROM epics WHERE id = ?", (target_epic,)).fetchone()
            if not existing:
                if target_epic == "epic-backlog":
                    _ensure_backlog_epic(conn)
                else:
                    return f"Epic '{target_epic}' not found. Create it first with pm_create_epic."

            if depends_on:
                invalid = _validate_dependencies(conn, depends_on)
                if invalid:
                    return f"Invalid depends_on story IDs: {invalid}"

            story_id = _next_id(conn, "stories", "story-")
            conn.execute(
                """INSERT INTO stories (id, epic_id, title, state, write_files, test_files, agent, model,
                   depends_on, needs_testing, needs_review)
                   VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, '[]', ?, ?)""",
                (
                    story_id, target_epic, title,
                    json.dumps(write_files or []),
                    json.dumps(test_files or []),
                    agent, model,
                    int(needs_testing), int(needs_review),
                )
            )
            if depends_on:
                _set_story_deps(conn, story_id, depends_on)

            created_tasks = []
            for task_title in tasks or []:
                task = _add_task_to_story(conn, story_id, task_title)
                created_tasks.append({"id": task["id"], "title": task_title, "state": "todo"})

            result = {
                "id": story_id, "epic_id": target_epic, "title": title,
                "state": "draft", "write_files": write_files or [],
                "agent": agent, "model": model,
            }
            if created_tasks:
                result["tasks"] = created_tasks
            return fmt_create_story(result)

    @mcp.tool()
    async def pm_add_task(
        title: str | None = None,
        story_id: str | None = None,
        write_files: list[str] | None = None,
        items: list[str] | None = None,
        blocked_by: str | None = None,
    ) -> str:
        """Add a task (or tasks) to a story with auto-generated IDs.

        story_id is optional — if omitted the tool searches open stories by keyword
        similarity. If 1 clear match is found the task is added there; if no match,
        a new story is created; if 2+ matches, candidates are returned for Claude to
        ask the user.

        Args:
            title: Single task title (omit if using items).
            story_id: Story to add the task to. Auto-detected from title if omitted.
            write_files: File paths hinting which story to target.
            items: Bulk list of task title strings (alternative to title).
            blocked_by: Optional task ID within the same story that blocks this one.
        """
        if not title and not items:
            return "Provide either 'title' for a single task or 'items' for bulk tasks."

        all_titles = items if items else [title]

        with _db_op() as conn:
            results = []
            for task_title in all_titles:
                target_story = story_id

                if not target_story:
                    matched, candidates = _find_best_story_match(conn, task_title)
                    if candidates:
                        return fmt_add_task({
                            "action": "needs_clarification",
                            "task": task_title,
                            "message": "Multiple plausible stories found. Specify story_id.",
                            "candidates": candidates,
                        })
                    if matched:
                        target_story = matched
                    else:
                        target_story = _create_story_for_task(conn, task_title, write_files)
                        results.append({"created_story": target_story})

                story = conn.execute("SELECT id FROM stories WHERE id = ?", (target_story,)).fetchone()
                if not story:
                    return f"Story '{target_story}' not found."

                task = _add_task_to_story(conn, target_story, task_title, blocked_by)
                results.append(task)

            if len(results) == 1:
                return fmt_add_task(results[0])
            return fmt_add_task({"created": results, "count": len(results)})

    @mcp.tool()
    async def pm_plan_items(
        items: list[str],
        epic_id: str | None = None,
        confirmed: bool = False,
        proposal: dict | None = None,
        proposal_id: str | None = None,
    ) -> str:
        """Bulk planning tool for unstructured todos. Groups items into stories and tasks.

        Two-phase flow:
        1. Phase 1 — Propose (confirmed=False): groups items and returns a JSON proposal.
        2. Phase 2 — Commit (confirmed=True, proposal=<from phase 1>): creates epics/stories/tasks.

        Args:
            items: Raw todo strings to plan.
            epic_id: Optional target epic for all proposed stories.
            confirmed: If True, commit the proposal to the DB.
            proposal: The proposal dict from Phase 1 (legacy fallback).
            proposal_id: The proposal_id returned by Phase 1 (preferred over proposal).
        """
        if confirmed and not proposal and not proposal_id:
            return "Pass 'proposal_id' (from Phase 1) when confirmed=True."

        with _db_op() as conn:
            if not confirmed:
                open_stories = conn.execute(
                    "SELECT id, title FROM stories WHERE state NOT IN ('done', 'shipped', 'archived')"
                ).fetchall()
                existing = [{"id": r["id"], "title": r["title"]} for r in open_stories]
                prop = _group_items(items, existing)

                if epic_id:
                    for s in prop["proposed_stories"]:
                        s["epic_id"] = epic_id

                pid = f"prop-{int(time.time())}"
                conn.execute(
                    "INSERT INTO pending_proposals (id, data) VALUES (?, ?)",
                    (pid, json.dumps(prop))
                )

                return fmt_plan_items({
                    "phase": "proposal",
                    "proposal_id": pid,
                    "item_count": len(items),
                    "story_count": len(prop["proposed_stories"]),
                    "proposed_stories": [s["title"] for s in prop["proposed_stories"]],
                    "instructions": (
                        "Review titles above. Call pm_plan_items with confirmed=True and proposal_id to commit."
                    ),
                })

            # Phase 2 — commit
            if proposal_id:
                row = conn.execute(
                    "SELECT data FROM pending_proposals WHERE id = ?", (proposal_id,)
                ).fetchone()
                if not row:
                    return f"proposal_id '{proposal_id}' not found or already used."
                prop = json.loads(row["data"])
                conn.execute("DELETE FROM pending_proposals WHERE id = ?", (proposal_id,))
            else:
                prop = proposal

            created_epics: list[dict] = []
            created_stories: list[dict] = []
            created_tasks: list[dict] = []

            for ep in prop.get("proposed_epics", []):
                ep_id = _next_id(conn, "epics", "epic-")
                conn.execute(
                    "INSERT INTO epics (id, title, branch, persistent, state) VALUES (?, ?, NULL, 0, 'active')",
                    (ep_id, ep["title"])
                )
                created_epics.append({"id": ep_id, "title": ep["title"]})
                for s in prop.get("proposed_stories", []):
                    if s.get("epic_id") == ep.get("temp_id"):
                        s["epic_id"] = ep_id

            target_epic = epic_id or "epic-backlog"
            existing_epic = conn.execute("SELECT id FROM epics WHERE id = ?", (target_epic,)).fetchone()
            if not existing_epic and target_epic == "epic-backlog":
                _ensure_backlog_epic(conn)

            for s in prop.get("proposed_stories", []):
                story_epic = s.get("epic_id") or target_epic
                ep_exists = conn.execute("SELECT id FROM epics WHERE id = ?", (story_epic,)).fetchone()
                if not ep_exists:
                    story_epic = target_epic

                sid = _next_id(conn, "stories", "story-")
                conn.execute(
                    """INSERT INTO stories (id, epic_id, title, state, write_files, agent, model,
                       depends_on, needs_testing, needs_review)
                       VALUES (?, ?, ?, 'draft', ?, NULL, NULL, '[]', 0, 0)""",
                    (sid, story_epic, s["title"], json.dumps(s.get("write_files") or []))
                )
                created_stories.append({"id": sid, "title": s["title"], "epic_id": story_epic})

                for task_title in s.get("tasks") or []:
                    task = _add_task_to_story(conn, sid, task_title)
                    created_tasks.append({"id": task["id"], "story_id": sid, "title": task_title})

            return fmt_plan_items({
                "phase": "committed",
                "created_epics": created_epics,
                "created_stories": created_stories,
                "created_tasks": created_tasks,
                "summary": (
                    f"Created {len(created_epics)} epic(s), "
                    f"{len(created_stories)} story(ies), "
                    f"{len(created_tasks)} task(s)."
                ),
            })

    @mcp.tool()
    async def pm_update_story(
        story_id: str,
        state: str | None = None,
        title: str | None = None,
        agent: str | None = None,
        model: str | None = None,
        write_files: list[str] | None = None,
        test_files: list[str] | None = None,
        branch: str | None = None,
        plan_file: str | None = None,
        move_to_epic: str | None = None,
        force: bool = False,
        archived: bool | None = None,
        worktree_path: str | None = None,
        worktree_active: bool | None = None,
    ) -> str:
        """Update story fields. Validates state transitions. Auto-timestamps on state changes.

        Args:
            story_id: Story to update.
            state: New state. Validates transition unless force=True.
            title: New title.
            agent: New agent type.
            model: New model.
            write_files: New list of write files.
            test_files: New list of test files for parallel test agent execution.
            branch: New branch name.
            plan_file: Path to the Claude-written plan file for this story.
            move_to_epic: Epic ID to move the story to.
            force: Skip state transition validation.
            archived: Manually archive (True) or unarchive (False) the story.
            worktree_path: Absolute path to the story's worktree (null to clear).
            worktree_active: Whether the worktree is currently active.
        """
        with _db_op() as conn:
            story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
            if not story:
                return f"Story '{story_id}' not found."

            sd = _story_to_dict(story)
            updates = []
            params: list = []

            if state is not None:
                if state not in STORY_STATES:
                    return f"Invalid state '{state}'. Valid: {sorted(STORY_STATES)}"
                err = _validate_transition(sd["state"], state, VALID_STORY_TRANSITIONS, force)
                if err:
                    return err
                updates.append("state = ?")
                params.append(state)

                if state == "in-progress" and not sd.get("started_at"):
                    updates.append("started_at = ?")
                    params.append(datetime.utcnow().isoformat())

                if state in TERMINAL_STATES:
                    updates.append("completed_at = ?")
                    params.append(datetime.utcnow().isoformat())
                    updates.append("archived = 1")

            if title is not None:
                updates.append("title = ?")
                params.append(title)

            if agent is not None:
                updates.append("agent = ?")
                params.append(agent)

            if model is not None:
                updates.append("model = ?")
                params.append(model)

            if write_files is not None:
                updates.append("write_files = ?")
                params.append(json.dumps(write_files))

            if test_files is not None:
                updates.append("test_files = ?")
                params.append(json.dumps(test_files))

            if branch is not None:
                updates.append("branch = ?")
                params.append(branch)

            if plan_file is not None:
                task_count = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE story_id = ?", (story_id,)
                ).fetchone()[0]
                if task_count == 0:
                    return f"Cannot set plan_file on '{story_id}': story has 0 tasks. Add tasks before attaching a plan."
                updates.append("plan_file = ?")
                params.append(plan_file)

            if move_to_epic is not None:
                epic = conn.execute("SELECT id FROM epics WHERE id = ?", (move_to_epic,)).fetchone()
                if not epic:
                    return f"Epic '{move_to_epic}' not found."
                updates.append("epic_id = ?")
                params.append(move_to_epic)

            if archived is not None:
                updates.append("archived = ?")
                params.append(int(archived))

            if worktree_path is not None:
                updates.append("worktree_path = ?")
                params.append(worktree_path)

            if worktree_active is not None:
                updates.append("worktree_active = ?")
                params.append(int(worktree_active))

            if not updates:
                return "No fields to update."

            params.append(story_id)
            conn.execute(
                f"UPDATE stories SET {', '.join(updates)} WHERE id = ?", params
            )

            updated = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
            return fmt_update_story(_story_to_dict(updated))

    @mcp.tool()
    async def pm_update_epic(
        epic_id: str,
        title: str | None = None,
        state: str | None = None,
        branch: str | None = None,
        pr_number: int | None = None,
        persistent: bool | None = None,
        milestone_order: int | None = None,
        target_date: str | None = None,
        description: str | None = None,
        auto_close: bool = False,
    ) -> str:
        """Update epic fields. Validates state transitions. Use auto_close=True to conditionally close if all stories are terminal.

        Args:
            epic_id: Epic to update.
            title: New title.
            state: New state ('active', 'done', 'shipped').
            branch: New branch name.
            pr_number: PR number.
            persistent: Whether the epic is persistent.
            milestone_order: Roadmap ordering (lower = higher priority).
            target_date: Target completion date (ISO format).
            description: Epic description.
            auto_close: If True, check if all non-archived stories are terminal and close if so. Respects persistent flag. Returns {closed, reason, remaining_count}.
        """
        with _db_op() as conn:
            epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
            if not epic:
                if auto_close:
                    return fmt_update_epic({"closed": False, "reason": f"Epic '{epic_id}' not found.", "remaining_count": 0})
                return f"Epic '{epic_id}' not found."

            ed = _epic_to_dict(epic)

            if auto_close:
                if ed.get("persistent"):
                    return fmt_update_epic({"closed": False, "reason": "Epic is persistent — will not auto-close.", "remaining_count": 0})
                if ed["state"] != "active":
                    return fmt_update_epic({"closed": False, "reason": f"Epic state is '{ed['state']}', not 'active'.", "remaining_count": 0})
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0 AND state NOT IN ('done', 'shipped')",
                    (epic_id,)
                ).fetchone()[0]
                if remaining > 0:
                    return fmt_update_epic({"closed": False, "reason": f"{remaining} story(ies) still active.", "remaining_count": remaining})
                conn.execute("UPDATE epics SET state = 'done' WHERE id = ?", (epic_id,))
                return fmt_update_epic({"closed": True, "reason": "All stories complete or archived.", "remaining_count": 0})

            updates = []
            params: list = []

            if state is not None:
                if state not in EPIC_STATES:
                    return f"Invalid state '{state}'. Valid: {sorted(EPIC_STATES)}"
                err = _validate_transition(ed["state"], state, VALID_EPIC_TRANSITIONS)
                if err:
                    return err
                updates.append("state = ?")
                params.append(state)

            if title is not None:
                updates.append("title = ?")
                params.append(title)

            if branch is not None:
                updates.append("branch = ?")
                params.append(branch)

            if pr_number is not None:
                updates.append("pr_number = ?")
                params.append(pr_number)

            if persistent is not None:
                updates.append("persistent = ?")
                params.append(int(persistent))

            if milestone_order is not None:
                updates.append("milestone_order = ?")
                params.append(milestone_order)

            if target_date is not None:
                updates.append("target_date = ?")
                params.append(target_date)

            if description is not None:
                updates.append("description = ?")
                params.append(description)

            if not updates:
                return "No fields to update."

            params.append(epic_id)
            conn.execute(
                f"UPDATE epics SET {', '.join(updates)} WHERE id = ?", params
            )

            updated = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
            return fmt_update_epic(_epic_to_dict(updated))

    @mcp.tool()
    async def pm_update_task(
        story_id: str,
        task_id: str,
        state: str | None = None,
        title: str | None = None,
    ) -> str:
        """Update a task's state or title within a story.

        Args:
            story_id: The story containing the task.
            task_id: The task ID (e.g., 't1').
            state: New task state ('todo', 'in-progress', 'done', 'blocked', 'skipped').
            title: New task title.
        """
        with _db_op() as conn:
            task = conn.execute(
                "SELECT * FROM tasks WHERE story_id = ? AND id = ?", (story_id, task_id)
            ).fetchone()
            if not task:
                return f"Task '{task_id}' not found in story '{story_id}'."

            updates = []
            params: list = []

            if state is not None:
                if state not in TASK_STATES:
                    return f"Invalid state '{state}'. Valid: {sorted(TASK_STATES)}"
                updates.append("state = ?")
                params.append(state)

            if title is not None:
                updates.append("title = ?")
                params.append(title)

            if not updates:
                return "No fields to update."

            params.extend([story_id, task_id])
            conn.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE story_id = ? AND id = ?", params
            )

            updated = conn.execute(
                "SELECT * FROM tasks WHERE story_id = ? AND id = ?", (story_id, task_id)
            ).fetchone()
            return fmt_update_task(dict(updated))

    return {
        "pm_create_epic": pm_create_epic,
        "pm_create_story": pm_create_story,
        "pm_add_task": pm_add_task,
        "pm_plan_items": pm_plan_items,
        "pm_update_story": pm_update_story,
        "pm_update_epic": pm_update_epic,
        "pm_update_task": pm_update_task,
    }
