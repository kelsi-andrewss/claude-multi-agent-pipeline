"""PM organize tools: pm_reorder and pm_housekeep."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from tools_pm_helpers import (
    _ensure_order_idx_column,
    _get_db,
    _group_items,
    _next_id,
    _score_stories_by_similarity,
    _story_to_dict,
)


def _renumber_epic_stories(conn, epic_id: str) -> None:
    """Assign sequential order_idx values (1, 2, 3...) to all non-archived stories in an epic."""
    rows = conn.execute(
        "SELECT id FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
        (epic_id,)
    ).fetchall()
    for i, row in enumerate(rows, start=1):
        conn.execute("UPDATE stories SET order_idx = ? WHERE id = ?", (i, row["id"]))


def register(mcp):
    @mcp.tool()
    async def pm_reorder(
        story_id: str | None = None,
        before_story_id: str | None = None,
        after_story_id: str | None = None,
        ranked: list[str] | None = None,
        epic_id: str | None = None,
    ) -> str:
        """Reorder stories within an epic. Either move one story relative to another, or supply a full ranked list.

        Args:
            story_id: The story to move (use with before_story_id or after_story_id).
            before_story_id: Place story_id immediately before this story.
            after_story_id: Place story_id immediately after this story.
            ranked: Full ordered list of story IDs for bulk ranking.
            epic_id: Scope for reorder when using anchor params.
        """
        conn = _get_db()
        try:
            _ensure_order_idx_column(conn)

            if ranked is not None:
                if not ranked:
                    return "ranked list is empty."
                unknowns = []
                for i, sid in enumerate(ranked, start=1):
                    row = conn.execute("SELECT id FROM stories WHERE id = ?", (sid,)).fetchone()
                    if not row:
                        unknowns.append(sid)
                        continue
                    conn.execute("UPDATE stories SET order_idx = ? WHERE id = ?", (i, sid))
                conn.commit()
                warnings = [f"Unknown story IDs skipped: {unknowns}"] if unknowns else []
                first_known = next((sid for sid in ranked if sid not in unknowns), None)
                if first_known:
                    epic_row = conn.execute("SELECT epic_id FROM stories WHERE id = ?", (first_known,)).fetchone()
                    target_epic = epic_row["epic_id"] if epic_row else None
                else:
                    target_epic = None
                result_stories = []
                if target_epic:
                    rows = conn.execute(
                        "SELECT id, title, state, order_idx FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
                        (target_epic,)
                    ).fetchall()
                    result_stories = [dict(r) for r in rows]
                return json.dumps({"mode": "reorder", "warnings": warnings, "stories": result_stories})

            if not story_id:
                return "Provide story_id (with before_story_id or after_story_id) or ranked."
            if before_story_id and after_story_id:
                return "Provide either before_story_id or after_story_id, not both."
            if not before_story_id and not after_story_id:
                return "Provide before_story_id or after_story_id when using story_id."

            anchor_id = before_story_id or after_story_id
            story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
            if not story:
                return f"Story '{story_id}' not found."
            anchor = conn.execute("SELECT * FROM stories WHERE id = ?", (anchor_id,)).fetchone()
            if not anchor:
                return f"Anchor story '{anchor_id}' not found."
            if story["epic_id"] != anchor["epic_id"]:
                return f"story_id and anchor must be in the same epic (got '{story['epic_id']}' and '{anchor['epic_id']}')."

            target_epic = story["epic_id"]

            has_nulls = conn.execute(
                "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0 AND order_idx IS NULL",
                (target_epic,)
            ).fetchone()[0]
            if has_nulls:
                _renumber_epic_stories(conn, target_epic)
                conn.commit()

            anchor_row = conn.execute("SELECT order_idx FROM stories WHERE id = ?", (anchor_id,)).fetchone()
            anchor_idx = anchor_row["order_idx"]

            if before_story_id:
                new_idx = anchor_idx - 1
            else:
                new_idx = anchor_idx + 1

            conn.execute("UPDATE stories SET order_idx = ? WHERE id = ?", (new_idx, story_id))
            conn.commit()

            collision = conn.execute(
                "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0 AND order_idx = ? AND id != ?",
                (target_epic, new_idx, story_id)
            ).fetchone()[0]
            if collision:
                _renumber_epic_stories(conn, target_epic)
                conn.commit()

            rows = conn.execute(
                "SELECT id, title, state, order_idx FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
                (target_epic,)
            ).fetchall()
            return json.dumps({"mode": "reorder", "epic_id": target_epic, "stories": [dict(r) for r in rows]})
        finally:
            conn.close()

    @mcp.tool()
    async def pm_housekeep(
        mode: str,
        archive_days: int = 30,
        stale_days: int = 14,
        confirmed: bool = False,
        proposal: dict | None = None,
        epic_id: str | None = None,
    ) -> str:
        """Housekeeping tool: triage unorganized work, cleanup done items, or regroup stories across epics.

        Args:
            mode: One of 'triage', 'cleanup', 'regroup'.
            archive_days: (cleanup) Archive done stories older than N days (default 30).
            stale_days: (cleanup) Surface in-progress stories older than N days (default 14).
            confirmed: (cleanup/regroup) If True, commit destructive changes.
            proposal: (regroup Phase 2) The proposal dict returned by Phase 1.
            epic_id: Scope triage/regroup to a single epic.
        """
        valid_modes = {"triage", "cleanup", "regroup"}
        if mode not in valid_modes:
            return f"Invalid mode '{mode}'. Valid modes: {sorted(valid_modes)}"

        conn = _get_db()
        try:
            _ensure_order_idx_column(conn)

            # Mode: triage
            if mode == "triage":
                epic_filter = " AND s.epic_id = ?" if epic_id else ""
                params_epic: list = [epic_id] if epic_id else []

                backlog_rows = conn.execute(
                    f"SELECT id, title, state, agent FROM stories s WHERE s.epic_id = 'epic-backlog' AND s.archived = 0{' AND s.epic_id = ?' if epic_id else ''}",
                    [epic_id] if epic_id else []
                ).fetchall()
                backlog_stories = [dict(r) for r in backlog_rows]

                unassigned_rows = conn.execute(
                    f"SELECT id, title, state, epic_id FROM stories s WHERE s.agent IS NULL AND s.archived = 0{epic_filter}",
                    params_epic
                ).fetchall()
                unassigned_stories = [dict(r) for r in unassigned_rows]

                draft_rows = conn.execute(
                    f"SELECT s.id, s.title, s.epic_id FROM stories s WHERE s.state = 'draft' AND s.archived = 0{epic_filter}",
                    params_epic
                ).fetchall()
                draft_without_tasks = []
                for row in draft_rows:
                    task_count = conn.execute(
                        "SELECT COUNT(*) FROM tasks WHERE story_id = ?", (row["id"],)
                    ).fetchone()[0]
                    if task_count == 0:
                        draft_without_tasks.append(dict(row))

                backlog_titles = [s["title"] for s in backlog_stories]
                clustering_proposal: dict = {}
                if backlog_titles:
                    open_stories_rows = conn.execute(
                        "SELECT id, title FROM stories WHERE state NOT IN ('done', 'shipped') AND archived = 0"
                    ).fetchall()
                    existing = [{"id": r["id"], "title": r["title"]} for r in open_stories_rows]
                    clustering_proposal = _group_items(backlog_titles, existing)

                suggested_moves = []
                non_backlog_epics = conn.execute(
                    "SELECT id, title FROM epics WHERE id != 'epic-backlog' AND state = 'active'"
                ).fetchall()
                for story in backlog_stories:
                    matches = _score_stories_by_similarity(story["title"], non_backlog_epics)
                    if matches:
                        best_score, best_epic, _ = matches[0]
                        suggested_moves.append({
                            "story_id": story["id"],
                            "story_title": story["title"],
                            "suggested_epic_id": best_epic,
                            "score": round(best_score, 2),
                            "reason": "keyword match",
                        })

                return json.dumps({
                    "mode": "triage",
                    "backlog_stories": backlog_stories,
                    "unassigned_stories": unassigned_stories,
                    "draft_without_tasks": draft_without_tasks,
                    "clustering_proposal": clustering_proposal,
                    "suggested_moves": suggested_moves,
                    "instructions": "Use pm_update_story(move_to_epic=...) or pm_plan_items to act on these.",
                })

            # Mode: cleanup
            if mode == "cleanup":
                if archive_days < 1:
                    return "archive_days must be >= 1."
                if stale_days < 1:
                    return "stale_days must be >= 1."

                now = datetime.utcnow()
                archive_cutoff = (now - timedelta(days=archive_days)).isoformat()
                stale_cutoff = (now - timedelta(days=stale_days)).isoformat()

                would_archive_rows = conn.execute(
                    """SELECT id, title, state, epic_id, completed_at
                       FROM stories
                       WHERE state IN ('done', 'shipped') AND archived = 0
                       AND completed_at IS NOT NULL AND completed_at < ?""",
                    (archive_cutoff,)
                ).fetchall()
                would_archive = [dict(r) for r in would_archive_rows]

                active_non_persistent = conn.execute(
                    "SELECT id, title FROM epics WHERE state = 'active' AND persistent = 0"
                ).fetchall()
                would_close = []
                for ep in active_non_persistent:
                    active_count = conn.execute(
                        "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0",
                        (ep["id"],)
                    ).fetchone()[0]
                    if active_count == 0:
                        would_close.append({"id": ep["id"], "title": ep["title"]})

                stale_rows = conn.execute(
                    """SELECT id, title, epic_id, started_at
                       FROM stories
                       WHERE state = 'in-progress' AND archived = 0
                       AND started_at IS NOT NULL AND started_at < ?""",
                    (stale_cutoff,)
                ).fetchall()
                stale_stories = [dict(r) for r in stale_rows]

                mismatch_rows = conn.execute(
                    """SELECT t.id as task_id, t.story_id, t.title as task_title,
                              s.state as story_state, s.title as story_title
                       FROM tasks t
                       JOIN stories s ON t.story_id = s.id
                       WHERE t.state = 'in-progress' AND s.state != 'in-progress' AND s.archived = 0"""
                ).fetchall()
                task_mismatches = [dict(r) for r in mismatch_rows]

                if not confirmed:
                    return json.dumps({
                        "mode": "cleanup",
                        "dry_run": True,
                        "would_archive_stories": would_archive,
                        "would_close_epics": would_close,
                        "stale_stories": stale_stories,
                        "task_mismatches": task_mismatches,
                    })

                archived_ids = [r["id"] for r in would_archive]
                for sid in archived_ids:
                    conn.execute("UPDATE stories SET archived = 1 WHERE id = ?", (sid,))

                closed_epic_ids = [ep["id"] for ep in would_close]
                for eid in closed_epic_ids:
                    remaining = conn.execute(
                        "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0", (eid,)
                    ).fetchone()[0]
                    if remaining == 0:
                        conn.execute("UPDATE epics SET state = 'done' WHERE id = ?", (eid,))

                conn.commit()
                return json.dumps({
                    "mode": "cleanup",
                    "dry_run": False,
                    "archived_stories": archived_ids,
                    "closed_epics": closed_epic_ids,
                    "stale_stories": stale_stories,
                    "task_mismatches": task_mismatches,
                })

            # Mode: regroup
            if mode == "regroup":
                if not confirmed:
                    epic_filter_sql = " AND s.epic_id = ?" if epic_id else ""
                    params_r: list = [epic_id] if epic_id else []

                    active_stories = conn.execute(
                        f"SELECT id, title, epic_id FROM stories s WHERE s.archived = 0{epic_filter_sql}",
                        params_r
                    ).fetchall()

                    titles = [r["title"] for r in active_stories]
                    story_map = {r["title"]: r for r in active_stories}

                    if not titles:
                        return json.dumps({"mode": "regroup", "phase": "proposal", "moves": [], "new_epics": [], "no_change": []})

                    open_stories_list = [{"id": r["id"], "title": r["title"]} for r in active_stories]
                    clustering = _group_items(titles, open_stories_list)

                    existing_epics = conn.execute(
                        "SELECT id, title FROM epics WHERE state = 'active'"
                    ).fetchall()

                    moves = []
                    new_epics_proposal = []
                    no_change = []

                    for cluster in clustering.get("proposed_stories", []):
                        cluster_title = cluster["title"]

                        cluster_story_ids = []
                        all_cluster_titles = [cluster_title] + cluster.get("tasks", [])
                        for ctitle in all_cluster_titles:
                            row = story_map.get(ctitle)
                            if row:
                                cluster_story_ids.append(row["id"])

                        if not cluster_story_ids:
                            continue

                        epic_matches = _score_stories_by_similarity(cluster_title, existing_epics)
                        best_score = epic_matches[0][0] if epic_matches else 0.0
                        best_epic_id = epic_matches[0][1] if epic_matches else None
                        best_epic_title = epic_matches[0][2] if epic_matches else None

                        for sid in cluster_story_ids:
                            story_row = conn.execute("SELECT id, epic_id FROM stories WHERE id = ?", (sid,)).fetchone()
                            if not story_row:
                                continue
                            current_epic = story_row["epic_id"]

                            if best_epic_id and best_epic_id != current_epic:
                                moves.append({
                                    "story_id": sid,
                                    "from_epic": current_epic,
                                    "to_epic": best_epic_id,
                                    "to_epic_title": best_epic_title,
                                    "score": round(best_score, 2),
                                })
                            elif not best_epic_id:
                                existing_new = next(
                                    (ne for ne in new_epics_proposal if ne.get("_cluster_title") == cluster_title),
                                    None
                                )
                                if not existing_new:
                                    new_epics_proposal.append({
                                        "_cluster_title": cluster_title,
                                        "title": cluster_title,
                                        "story_ids": cluster_story_ids,
                                    })
                            else:
                                no_change.append({"story_id": sid, "epic_id": current_epic})

                    clean_new_epics = [
                        {"title": ne["title"], "story_ids": ne["story_ids"]}
                        for ne in new_epics_proposal
                    ]

                    return json.dumps({
                        "mode": "regroup",
                        "phase": "proposal",
                        "moves": moves,
                        "new_epics": clean_new_epics,
                        "no_change": no_change,
                        "instructions": (
                            "Review the proposal, then call pm_housekeep(mode='regroup', confirmed=True, proposal=<this>) "
                            "to commit. You may modify the proposal before passing it back."
                        ),
                    })

                # Phase 2: commit
                if not proposal:
                    return "Pass the proposal dict from Phase 1 when confirmed=True."

                moved = []
                skipped = []
                created_epics = []

                new_epic_id_map: dict[str, str] = {}
                for ne in proposal.get("new_epics", []):
                    new_title = ne.get("title", "")
                    if not new_title:
                        continue
                    new_eid = _next_id(conn, "epics", "epic-")
                    conn.execute(
                        "INSERT INTO epics (id, title, branch, persistent, state) VALUES (?, ?, NULL, 0, 'active')",
                        (new_eid, new_title)
                    )
                    created_epics.append({"id": new_eid, "title": new_title})
                    new_epic_id_map[new_title] = new_eid

                    for sid in ne.get("story_ids", []):
                        story_row = conn.execute("SELECT id FROM stories WHERE id = ?", (sid,)).fetchone()
                        if not story_row:
                            skipped.append({"story_id": sid, "reason": "story no longer exists"})
                            continue
                        conn.execute("UPDATE stories SET epic_id = ? WHERE id = ?", (new_eid, sid))
                        moved.append({"story_id": sid, "to_epic": new_eid})

                for move in proposal.get("moves", []):
                    sid = move.get("story_id")
                    from_epic = move.get("from_epic")
                    to_epic = move.get("to_epic")
                    if not sid or not to_epic:
                        continue
                    story_row = conn.execute("SELECT id, epic_id FROM stories WHERE id = ?", (sid,)).fetchone()
                    if not story_row:
                        skipped.append({"story_id": sid, "reason": "story no longer exists"})
                        continue
                    if story_row["epic_id"] != from_epic:
                        skipped.append({"story_id": sid, "reason": f"epic changed (now {story_row['epic_id']})"})
                        continue
                    epic_exists = conn.execute("SELECT id FROM epics WHERE id = ?", (to_epic,)).fetchone()
                    if not epic_exists:
                        skipped.append({"story_id": sid, "reason": f"target epic '{to_epic}' not found"})
                        continue
                    conn.execute("UPDATE stories SET epic_id = ? WHERE id = ?", (to_epic, sid))
                    moved.append({"story_id": sid, "to_epic": to_epic})

                conn.commit()
                return json.dumps({
                    "mode": "regroup",
                    "phase": "committed",
                    "moved": moved,
                    "created_epics": created_epics,
                    "skipped": skipped,
                })

            return f"Unhandled mode '{mode}'."
        finally:
            conn.close()
