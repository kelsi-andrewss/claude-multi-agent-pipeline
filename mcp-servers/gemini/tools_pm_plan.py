"""PM plan tools: pm_plan_story, pm_plan_stories, pm_plan_bulk, pm_critique, pm_check_conflicts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from constants import MAX_CODE_BYTES
from format_response import (
    fmt_check_conflicts,
    fmt_critique,
    fmt_plan_bulk,
    fmt_plan_stories,
    fmt_plan_story,
)
from gemini_client import _discover_files, _gemini, _load_audit_context, _read_files_within_budget
from tools_pm_helpers import _add_task_to_story, _apply_plan_to_story, _build_plan_prompt, _db_op, _set_story_deps, _story_to_dict


def register(mcp):
    @mcp.tool()
    async def pm_plan_story(
        story_id: str,
        paths: list[str] | None = None,
        project_root: str | None = None,
        context: str | None = None,
    ) -> str:
        """Plan a single story: generate tasks, agent assignment, write_files, and dependencies.

        Args:
            story_id: The story to plan.
            paths: Source file paths to pass as codebase context.
            project_root: Absolute path to the project root.
            context: Optional requirements/PRD text to inject into the planning prompt.
        """
        _root = Path(project_root).resolve() if project_root else None
        with _db_op() as conn:
            story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
            if not story:
                return fmt_plan_story({"error": f"Story '{story_id}' not found."})
            sd = _story_to_dict(story)

            audit_context = _load_audit_context(root=_root)
            files = _discover_files(paths, root=_root)
            code_content, _ = _read_files_within_budget(files, MAX_CODE_BYTES, root=_root)

            open_stories = conn.execute(
                "SELECT id, title, state FROM stories WHERE state NOT IN ('done','shipped') AND archived = 0 AND id != ?",
                (story_id,)
            ).fetchall()
            open_stories_text = "\n".join(
                f"- {r['id']}: {r['title']} [{r['state']}]" for r in open_stories
            ) or "(none)"

            subject = (
                f"Story ID: {sd['id']}\n"
                f"Title: {sd['title']}\n"
                f"Current agent: {sd.get('agent') or 'unassigned'}\n"
                f"Current write_files: {sd.get('write_files') or []}\n\n"
                f"Other open stories (for dependency awareness):\n{open_stories_text}\n\n"
                "Return a single JSON object (not an array) with fields: "
                "agent, write_files, read_files, tasks, parallel_group, depends_on."
            )

            prompt = _build_plan_prompt(subject, audit_context, code_content, user_context=context)
            raw = await _gemini(prompt)

            try:
                plan_data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return fmt_plan_story({"error": "Gemini returned malformed JSON.", "raw": raw[:2000]})

            for task_title in plan_data.get("tasks", []):
                _add_task_to_story(conn, story_id, task_title)
            conn.execute(
                "UPDATE stories SET agent = ?, write_files = ? WHERE id = ?",
                (plan_data.get("agent"), json.dumps(plan_data.get("write_files", [])), story_id)
            )
            depends_on = plan_data.get("depends_on", [])
            dep_warnings: list[str] = []
            if depends_on:
                dep_warnings = _set_story_deps(conn, story_id, depends_on)
            result = {
                "mode": "story",
                "story_id": story_id,
                "title": sd["title"],
                "agent": plan_data.get("agent"),
                "write_files": plan_data.get("write_files", []),
                "tasks_created": len(plan_data.get("tasks", [])),
            }
            if dep_warnings:
                result["dep_warnings"] = dep_warnings
            return fmt_plan_story(result)

    @mcp.tool()
    async def pm_plan_stories(
        story_ids: list[str] | None = None,
        epic_id: str | None = None,
        stories: list[dict] | None = None,
        paths: list[str] | None = None,
        project_root: str | None = None,
        context: str | None = None,
    ) -> str:
        """Plan multiple stories: generate tasks, agents, and execution order. Provide story_ids explicitly or epic_id to plan all draft stories in an epic.

        Args:
            story_ids: List of story IDs to plan.
            epic_id: Plan all draft/ready stories in this epic (used when story_ids not provided).
            stories: Per-story path scoping. List of {story_id, paths} dicts for individual file context per story.
            paths: Source file paths for shared codebase context.
            project_root: Absolute path to the project root.
            context: Optional requirements/PRD text to inject into the planning prompt.
        """
        _root = Path(project_root).resolve() if project_root else None
        with _db_op() as conn:
            per_story_paths: dict[str, list[str]] | None = None
            if stories:
                story_ids = [s["story_id"] for s in stories]
                per_story_paths = {s["story_id"]: s.get("paths", []) for s in stories}

            # If epic_id provided and no story_ids, fetch draft stories from epic
            if not story_ids and epic_id:
                epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
                if not epic:
                    return fmt_plan_stories({"error": f"Epic '{epic_id}' not found."})

                draft_stories = conn.execute(
                    "SELECT * FROM stories WHERE epic_id = ? AND state IN ('draft','ready') AND archived = 0",
                    (epic_id,)
                ).fetchall()
                if not draft_stories:
                    return fmt_plan_stories({"mode": "epic", "epic_id": epic_id, "message": "No draft/ready stories found in this epic."})
                story_ids = [_story_to_dict(s)["id"] for s in draft_stories]

            if not story_ids:
                return fmt_plan_stories({"error": "Provide story_ids or epic_id."})

            audit_context = _load_audit_context(root=_root)
            if not per_story_paths:
                files = _discover_files(paths, root=_root)
                code_content, _ = _read_files_within_budget(files, MAX_CODE_BYTES, root=_root)
            else:
                code_content = ""

            errors = []
            story_list = []
            for sid in story_ids:
                row = conn.execute("SELECT * FROM stories WHERE id = ?", (sid,)).fetchone()
                if not row:
                    errors.append(f"Story '{sid}' not found.")
                    continue
                sd = _story_to_dict(row)
                if sd["state"] not in ("draft", "ready"):
                    errors.append(f"Story '{sid}' has state '{sd['state']}' — skipping (only draft/ready planned).")
                    continue
                story_list.append(sd)

            if not story_list:
                return fmt_plan_stories({"error": "No plannable stories found.", "details": errors})

            # Build epic context if available
            epic_prefix = ""
            if epic_id:
                epic = conn.execute("SELECT title FROM epics WHERE id = ?", (epic_id,)).fetchone()
                if epic:
                    epic_prefix = f"Epic ID: {epic_id}\nEpic title: {epic['title']}\n\n"

            subject_lines = [f"- Story {s['id']}: {s['title']}" for s in story_list]
            subject = (
                epic_prefix
                + "Stories to plan (return a JSON array, one object per story in the same order):\n"
                + "\n".join(subject_lines)
                + "\n\nEach array element must have: story_id, agent, write_files, read_files, tasks, parallel_group, depends_on."
            )

            if per_story_paths:
                plans = []
                for s in story_list:
                    sid = s["id"]
                    sp = per_story_paths.get(sid, [])
                    story_files = _discover_files(sp if sp else None, root=_root)
                    story_code, _ = _read_files_within_budget(story_files, MAX_CODE_BYTES, root=_root)
                    story_subject = (
                        f"Story ID: {sid}\n"
                        f"Title: {s['title']}\n"
                        f"Current agent: {s.get('agent') or 'unassigned'}\n"
                        f"Current write_files: {s.get('write_files') or []}\n\n"
                        "Return a single JSON object (not an array) with fields: "
                        "story_id, agent, write_files, read_files, tasks, parallel_group, depends_on."
                    )
                    story_prompt = _build_plan_prompt(story_subject, audit_context, story_code, user_context=context)
                    raw = await _gemini(story_prompt)
                    try:
                        plan_data = json.loads(raw)
                        if isinstance(plan_data, list):
                            plan_data = plan_data[0]
                    except (json.JSONDecodeError, ValueError):
                        return fmt_plan_stories({"error": f"Gemini returned malformed JSON for {sid}.", "raw": raw[:2000]})
                    plans.append(plan_data)
            else:
                prompt = _build_plan_prompt(subject, audit_context, code_content, user_context=context)
                raw = await _gemini(prompt)
                try:
                    plans = json.loads(raw)
                    if not isinstance(plans, list):
                        plans = [plans]
                except (json.JSONDecodeError, ValueError):
                    return fmt_plan_stories({"error": "Gemini returned malformed JSON.", "raw": raw[:2000]})

            plans_by_id = {}
            for plan_data in plans:
                pid = plan_data.get("story_id")
                if pid:
                    plans_by_id[pid] = plan_data

            summary = []
            for s in story_list:
                sid = s["id"]
                plan_data = plans_by_id.get(sid)
                if plan_data is None:
                    summary.append({"story_id": sid, "title": s["title"], "error": "No matching plan returned by Gemini."})
                    continue
                summary.append({"title": s["title"], **_apply_plan_to_story(conn, sid, plan_data)})

            result = {"mode": "multi-story", "stories": summary}
            if epic_id:
                result["epic_id"] = epic_id
            if errors:
                result["warnings"] = errors
            return fmt_plan_stories(result)

    @mcp.tool()
    async def pm_plan_bulk(
        paths: list[str] | None = None,
        project_root: str | None = None,
        context: str | None = None,
    ) -> str:
        """Generate a full roadmap JSON for all active epics and their stories.

        Args:
            paths: Source file paths to pass as codebase context.
            project_root: Absolute path to the project root.
            context: Optional requirements/PRD text to inject into the planning prompt.
        """
        _root = Path(project_root).resolve() if project_root else None
        with _db_op() as conn:
            audit_context = _load_audit_context(root=_root)
            files = _discover_files(paths, root=_root)
            code_content, _ = _read_files_within_budget(files, MAX_CODE_BYTES, root=_root)

            active_epics = conn.execute("SELECT * FROM epics WHERE state = 'active'").fetchall()

            from tools_pm_helpers import _epic_to_dict
            all_stories = conn.execute(
                "SELECT * FROM stories WHERE state NOT IN ('done','shipped','archived') AND archived = 0 "
                "ORDER BY epic_id, id"
            ).fetchall()

            epic_map: dict[str, dict] = {}
            for epic in active_epics:
                ed = _epic_to_dict(epic)
                epic_map[ed["id"]] = {**ed, "stories": []}

            for story in all_stories:
                sd = _story_to_dict(story)
                eid = sd.get("epic_id", "")
                if eid in epic_map:
                    epic_map[eid]["stories"].append(sd)

            subject_parts = []
            for eid, edata in epic_map.items():
                subject_parts.append(f"Epic {eid}: {edata['title']}")
                for s in edata["stories"]:
                    subject_parts.append(f"  - Story {s['id']}: {s['title']} [{s['state']}]")

            subject = (
                "Produce a full roadmap JSON with this structure:\n"
                '{"epics": [{"id": ..., "title": ..., "stories": [{"id": ..., "title": ..., '
                '"agent": ..., "parallel_group": ..., "depends_on": [...], "tasks": [...]}]}], '
                '"execution_plan": {"parallel_groups": [{"group": 1, "stories": [...], '
                '"can_run_simultaneously": true}], "total_stories": N}}\n\n'
                "Stories to plan:\n" + "\n".join(subject_parts)
            )

            prompt = _build_plan_prompt(subject, audit_context, code_content, user_context=context)
            raw = await _gemini(prompt)

            try:
                roadmap = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return fmt_plan_bulk({"error": "Gemini returned malformed JSON.", "raw": raw[:2000]})

            roadmap["generated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            roadmap["mode"] = "bulk"
            return fmt_plan_bulk(roadmap)

    @mcp.tool()
    async def pm_critique(
        story_ids: list[str],
        plan_files: list[str] | None = None,
        project_root: str | None = None,
        model: str | None = None,
    ) -> str:
        """Critique plan files against ORCHESTRATION.md section 6 checklist. Returns structured findings per story.

        Checks: missing files, scope creep, conflicts with in-progress stories, project conventions,
        edge cases, existing utilities, past decisions.

        Args:
            story_ids: List of story IDs to critique.
            plan_files: Optional explicit plan file paths. If omitted, reads plan_file from each story.
            project_root: Absolute path to the project root. Defaults to the server's working directory.
            model: Optional Gemini model ID override.
        """
        _root = Path(project_root).resolve() if project_root else None
        with _db_op(readonly=True) as conn:
            stories_info = []
            for i, sid in enumerate(story_ids):
                row = conn.execute("SELECT * FROM stories WHERE id = ?", (sid,)).fetchone()
                if not row:
                    stories_info.append({"story_id": sid, "error": "not found"})
                    continue
                sd = _story_to_dict(row)

                plan_path = None
                if plan_files and i < len(plan_files):
                    plan_path = plan_files[i]
                elif sd.get("plan_file"):
                    plan_path = sd["plan_file"]

                plan_content = ""
                if plan_path:
                    p = Path(plan_path).expanduser()
                    if not p.is_absolute():
                        p = Path.home() / ".claude" / plan_path
                    if p.exists():
                        plan_content = p.read_text(encoding="utf-8")

                stories_info.append({
                    "story_id": sid,
                    "title": sd["title"],
                    "write_files": sd.get("write_files", []),
                    "agent": sd.get("agent"),
                    "plan_content": plan_content,
                })

            in_progress = conn.execute(
                "SELECT id, title, write_files FROM stories WHERE state = 'in-progress' AND archived = 0"
            ).fetchall()
            in_progress_info = []
            for r in in_progress:
                wf = r["write_files"]
                if wf and isinstance(wf, str):
                    try:
                        wf = json.loads(wf)
                    except json.JSONDecodeError:
                        wf = []
                in_progress_info.append({"id": r["id"], "title": r["title"], "write_files": wf or []})

            decisions = conn.execute(
                "SELECT d.*, GROUP_CONCAT(ds.scope_type || ':' || ds.scope_value, '; ') as scopes_str "
                "FROM decisions d LEFT JOIN decision_scopes ds ON d.id = ds.decision_id "
                "WHERE d.status = 'active' GROUP BY d.id ORDER BY d.decided_at DESC LIMIT 50"
            ).fetchall()
            decisions_text = "\n".join(
                f"- {dict(d)['id']}: {dict(d)['title']} — chose: {dict(d)['chose']}"
                + (f" (scopes: {dict(d)['scopes_str']})" if dict(d).get('scopes_str') else "")
                for d in decisions
            ) or "(none)"

            orch_path = Path.home() / ".claude" / "ORCHESTRATION.md"
            orch_content = ""
            if orch_path.exists():
                full_orch = orch_path.read_text(encoding="utf-8")
                start = full_orch.find("## 6.")
                if start >= 0:
                    end = full_orch.find("\n## 7.", start)
                    orch_content = full_orch[start:end] if end > start else full_orch[start:]

            critique_system = (
                "You are a senior architect critiquing implementation plans. "
                "For each story, check against the critique checklist below and return a JSON array "
                "of finding objects.\n\n"
                "Each finding: {\"story_id\": ..., \"severity\": \"blocking|warning|note\", "
                "\"category\": \"missing_files|scope_creep|conflict|convention|edge_case|existing_utility|past_decision\", "
                "\"description\": ..., \"suggestion\": ...}\n\n"
                "Return ONLY valid JSON. No prose, no markdown."
            )

            stories_block = ""
            for s in stories_info:
                if "error" in s:
                    continue
                stories_block += (
                    f"\n### Story {s['story_id']}: {s['title']}\n"
                    f"Agent: {s['agent']}\n"
                    f"Write files: {s['write_files']}\n"
                )
                if s["plan_content"]:
                    stories_block += f"\nPlan:\n{s['plan_content'][:5000]}\n"

            full_prompt = (
                f"## Critique Checklist\n\n{orch_content}\n\n"
                f"## Stories Under Review\n{stories_block}\n\n"
                f"## In-Progress Stories (check for conflicts)\n{json.dumps(in_progress_info)}\n\n"
                f"## Active Decisions (check for contradictions)\n{decisions_text}"
            )

            raw = await _gemini(full_prompt, model=model, system_instruction=critique_system)

            if raw.startswith("[gemini error") or raw.startswith("[gemini parse error"):
                return fmt_critique({"error": raw, "story_ids": story_ids})

            try:
                findings = json.loads(raw)
                if not isinstance(findings, list):
                    findings = [findings]
            except json.JSONDecodeError:
                return fmt_critique({"error": "Gemini returned malformed JSON.", "raw": raw[:2000], "story_ids": story_ids})

            return fmt_critique({
                "story_ids": story_ids,
                "findings": findings,
                "finding_count": len(findings),
                "blocking_count": sum(1 for f in findings if f.get("severity") == "blocking"),
            })

    @mcp.tool()
    async def pm_check_conflicts(story_ids: list[str]) -> str:
        """Check write-file overlaps between stories. Returns conflict map and parallel/sequential classification.

        Args:
            story_ids: List of story IDs to check for conflicts.
        """
        with _db_op(readonly=True) as conn:
            stories_data = {}
            stories_read_data = {}
            for sid in story_ids:
                row = conn.execute("SELECT id, write_files, read_files FROM stories WHERE id = ?", (sid,)).fetchone()
                if not row:
                    continue
                wf = row["write_files"]
                if wf and isinstance(wf, str):
                    try:
                        wf = json.loads(wf)
                    except json.JSONDecodeError:
                        wf = []
                stories_data[sid] = set(wf or [])

                rf = row["read_files"] if "read_files" in row.keys() else None
                if rf and isinstance(rf, str):
                    try:
                        rf = json.loads(rf)
                    except json.JSONDecodeError:
                        rf = []
                stories_read_data[sid] = set(rf or [])

            # Write-write conflicts
            conflicts = []
            file_to_stories: dict[str, list[str]] = {}
            for sid, files in stories_data.items():
                for f in files:
                    file_to_stories.setdefault(f, []).append(sid)

            for f, sids in file_to_stories.items():
                if len(sids) > 1:
                    conflicts.append({"file": f, "stories": sids})

            # Write-read conflicts
            read_conflicts = []
            for writer_id, write_files in stories_data.items():
                for reader_id, read_files in stories_read_data.items():
                    if writer_id == reader_id:
                        continue
                    overlap = write_files & read_files
                    for f in overlap:
                        read_conflicts.append({"file": f, "writer": writer_id, "reader": reader_id})

            conflicting_ids = set()
            for c in conflicts:
                conflicting_ids.update(c["stories"])
            # Readers must run after their writers
            for rc in read_conflicts:
                conflicting_ids.add(rc["reader"])

            safe_parallel = [sid for sid in story_ids if sid in stories_data and sid not in conflicting_ids]
            sequential = [sid for sid in story_ids if sid in conflicting_ids]

            return fmt_check_conflicts({
                "conflicts": conflicts,
                "read_conflicts": read_conflicts,
                "safe_parallel": safe_parallel,
                "sequential": sequential,
            })
