"""Slim MCP responses: one-liner terminal output + detail files in /tmp/gemini/.

Every PM tool returns at most one line to the terminal. Detail-heavy responses
write markdown to /tmp/gemini/<name>.md and append " → <path>" to the one-liner.
"""
# TODO: 850+ lines / 21 fmt_* functions — split into format_pm.py and format_analysis.py when this exceeds ~1000 lines.

from __future__ import annotations

import json
import os

DETAIL_DIR = "/tmp/gemini"


def _write_detail(filename: str, content: str) -> str:
    os.makedirs(DETAIL_DIR, exist_ok=True)
    path = os.path.join(DETAIL_DIR, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


def _abbr_agent(agent: str | None) -> str:
    return {"quick-fixer": "qf", "architect": "arch", "manual": "manual"}.get(
        agent or "", agent or "—"
    )


def _safe(val, default="—"):
    return val if val is not None else default


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _is_error(data) -> bool:
    return isinstance(data, dict) and "error" in data


def _fmt_error(data: dict) -> str:
    return f"Error: {data['error']}"


# ===========================================================================
# SIMPLE RESPONSES (no detail file)
# ===========================================================================


def fmt_update_story(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)
    sid = data.get("id", "?")
    state = data.get("state", "?")
    agent = _abbr_agent(data.get("agent"))
    wf = data.get("write_files") or []
    plan = data.get("plan_file") or ""
    parts = [f"Updated {sid} [{state}] {agent}"]
    if wf:
        parts.append(f"{len(wf)} files")
    if plan:
        parts.append(f"plan: {plan}")
    return " — ".join(parts)


def fmt_update_task(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)
    sid = data.get("story_id", "?")
    tid = data.get("id", "?")
    title = data.get("title", "")
    state = data.get("state", "?")
    return f"Updated {sid}/{tid}: {title} [{state}]"


def fmt_update_epic(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)
    # auto_close response shape
    if "closed" in data:
        closed = data["closed"]
        reason = data.get("reason", "")
        if closed:
            return f"Epic auto-closed: {reason}"
        return f"Epic not closed: {reason}"
    eid = data.get("id", "?")
    state = data.get("state", "?")
    title = data.get("title", "?")
    return f"Updated {eid} [{state}]: {title}"


def fmt_add_task(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)
    # Needs clarification
    if data.get("action") == "needs_clarification":
        candidates = data.get("candidates", [])
        return f"Needs clarification: {len(candidates)} candidate stories for '{data.get('task', '?')}'"
    # Bulk
    if "created" in data:
        count = data.get("count", len(data["created"]))
        return f"Added {count} tasks"
    # Single task
    tid = data.get("id", "?")
    sid = data.get("story_id", "?")
    title = data.get("title", "")
    state = data.get("state", "todo")
    return f"Added {sid}/{tid}: {title} [{state}]"


def fmt_create_story(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)
    sid = data.get("id", "?")
    title = data.get("title", "?")
    state = data.get("state", "draft")
    agent = _abbr_agent(data.get("agent"))
    return f"Created {sid}: {title} [{state}, {agent}]"


def fmt_create_epic(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)
    eid = data.get("id", "?")
    title = data.get("title", "?")
    state = data.get("state", "active")
    return f"Created {eid}: {title} [{state}]"


def fmt_dev_branch(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)
    return data.get("dev_branch", json.dumps(data))


# ===========================================================================
# DETAIL RESPONSES (one-liner + /tmp/gemini/<file>.md)
# ===========================================================================


def _fmt_ship_multi(data: dict) -> str:
    epics = data["epics"]
    is_proposal = data.get("phase") == "proposal"
    pid = data.get("proposal_id", "")
    total_stories = 0

    md = "# pm_ship — multi-epic"
    if is_proposal:
        md += " proposal"
    md += "\n\n"

    if is_proposal and pid:
        md += f"Proposal {pid}\n\n"

    for epic in epics:
        eid = epic.get("epic_id", "?")
        etitle = epic.get("epic_title", "")
        stories = epic.get("proposed_stories" if is_proposal else "stories", [])
        total_stories += len(stories)

        md += f"## {eid}: {etitle}\n\n"

        if is_proposal:
            md += "| # | Title | Agent |\n|---|-------|-------|\n"
            for i, s in enumerate(stories, 1):
                t = s.get("title", "?") if isinstance(s, dict) else str(s)
                a = _abbr_agent(s.get("agent")) if isinstance(s, dict) else "—"
                md += f"| {i} | {t} | {a} |\n"
        else:
            md += "| Story | Title | Agent | Write files |\n|-------|-------|-------|-------------|\n"
            for s in stories:
                sid = s.get("id", "?")
                t = s.get("title", "?")
                a = _abbr_agent(s.get("agent"))
                wf = s.get("write_files", [])
                wf_str = ", ".join(wf) if wf else "—"
                md += f"| {sid} | {t} | {a} | {wf_str} |\n"

        md += "\n"

    epic_count = len(epics)
    md += f"{epic_count} epics, {total_stories} total stories.\n"

    if is_proposal:
        md += "\nCall with proposal_id to commit.\n"

    path = _write_detail("ship-multi.md", md)

    if is_proposal:
        return f"Proposal {pid}: {epic_count} epics, {total_stories} stories. → {path}"
    return f"Created {epic_count} epics ({total_stories} stories). → {path}"


def fmt_ship(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    if data.get("epics"):
        return _fmt_ship_multi(data)

    epic_id = data.get("epic_id", "?")
    epic_title = data.get("epic_title", "")

    # Proposal phase
    if data.get("phase") == "proposal":
        stories = data.get("proposed_stories", [])
        count = data.get("story_count", len(stories))
        pid = data.get("proposal_id", "?")
        md = f"# pm_ship proposal — {epic_id}\n\n"
        md += f'Proposal {pid} for "{epic_title}"\n\n'
        md += "| # | Title | Agent |\n|---|-------|-------|\n"
        for i, s in enumerate(stories, 1):
            t = s.get("title", "?") if isinstance(s, dict) else str(s)
            a = _abbr_agent(s.get("agent")) if isinstance(s, dict) else "—"
            md += f"| {i} | {t} | {a} |\n"
        md += f"\n{count} stories proposed. Call with proposal_id to commit.\n"
        path = _write_detail(f"ship-{epic_id}.md", md)
        return f"Proposal {pid}: {count} stories for {epic_title}. → {path}"

    # Commit / resume
    stories = data.get("stories", [])
    count = len(stories)
    md = f"# pm_ship — {epic_id}\n\n"
    md += f'Created {epic_id}: "{epic_title}"\n\n'
    md += "| Story | Title | Agent | Write files |\n|-------|-------|-------|-------------|\n"
    for s in stories:
        sid = s.get("id", "?")
        t = s.get("title", "?")
        a = _abbr_agent(s.get("agent"))
        wf = s.get("write_files", [])
        wf_str = ", ".join(wf) if wf else "—"
        md += f"| {sid} | {t} | {a} | {wf_str} |\n"
    md += f"\n{count} stories, all draft.\n"
    path = _write_detail(f"ship-{epic_id}.md", md)
    return f"Created {epic_id} ({count} stories). → {path}"


def fmt_get_story(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    sid = data.get("id", "?")
    title = data.get("title", "?")
    state = data.get("state", "?")
    agent = _abbr_agent(data.get("agent"))
    epic_id = data.get("epic_id", "?")
    wf = data.get("write_files") or []
    tasks = data.get("tasks") or []
    depends = data.get("depends_on") or []
    blocks = data.get("blocks") or []
    branch = data.get("branch")
    plan_file = data.get("plan_file")

    md = f"# {sid}\n\n"
    md += f'"{title}" [{state}]\n'
    md += f"Agent: {agent} | Epic: {epic_id}\n"
    if branch:
        md += f"Branch: {branch}\n"
    if plan_file:
        md += f"Plan: {plan_file}\n"
    md += "\n"

    if wf:
        md += "Write files:\n"
        for f in wf:
            md += f"- {f}\n"
        md += "\n"

    dep_str = ", ".join(depends) if depends else "(none)"
    blk_str = ", ".join(b["id"] for b in blocks) if blocks else "(none)"
    md += f"Depends: {dep_str} | Blocks: {blk_str}\n\n"

    done_count = sum(1 for t in tasks if t.get("state") == "done")
    md += f"Tasks ({len(tasks)}, {done_count} done):\n"
    for t in tasks:
        ts = t.get("state", "?")
        tt = t.get("title", "?")
        md += f"- [{ts}] {tt}\n"

    path = _write_detail(f"story-{sid.replace('story-', '')}.md", md)
    return f"{sid} [{state}] {agent} — {len(wf)} files, {len(tasks)} tasks. → {path}"


def fmt_get_epic(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    eid = data.get("id", "?")
    title = data.get("title", "?")
    state = data.get("state", "?")
    stories = data.get("stories") or []
    done = sum(1 for s in stories if s.get("state") in ("done", "shipped"))

    md = f"# {eid}\n\n"
    md += f'"{title}" [{state}]\n\n'
    if stories:
        md += "| Story | Title | State | Agent | Files |\n|-------|-------|-------|-------|-------|\n"
        for s in stories:
            sid = s.get("id", "?")
            st = s.get("title", "?")
            ss = s.get("state", "?")
            sa = _abbr_agent(s.get("agent"))
            wf = s.get("write_files") or []
            md += f"| {sid} | {st} | {ss} | {sa} | {len(wf)} |\n"
        md += "\n"
    md += f"{len(stories)} stories ({done} done).\n"

    path = _write_detail(f"epic-{eid.replace('epic-', '')}.md", md)
    return f"{eid} [{state}] — {len(stories)} stories ({done} done). → {path}"


def fmt_list_stories(data: list) -> str:
    if isinstance(data, dict) and _is_error(data):
        return _fmt_error(data)
    if not isinstance(data, list):
        return json.dumps(data)

    stories = data
    count = len(stories)
    if count == 0:
        return "0 stories."

    # Count by state
    by_state: dict[str, int] = {}
    for s in stories:
        st = s.get("state", "?")
        by_state[st] = by_state.get(st, 0) + 1
    state_summary = ", ".join(f"{c} {st}" for st, c in sorted(by_state.items()))

    # Determine epic for filename
    epic_ids = set(s.get("epic_id", "") for s in stories)
    if len(epic_ids) == 1:
        eid = epic_ids.pop()
        filename = f"list-{eid.replace('epic-', 'epic-')}.md"
    else:
        filename = "list-stories.md"

    md = "# Stories\n\n"
    md += "| Story | Title | State | Agent | Epic | Files |\n"
    md += "|-------|-------|-------|-------|------|-------|\n"
    for s in stories:
        sid = s.get("id", "?")
        t = s.get("title", "?")
        st = s.get("state", "?")
        a = _abbr_agent(s.get("agent"))
        e = s.get("epic_id", "?")
        wf = s.get("write_files") or []
        md += f"| {sid} | {t} | {st} | {a} | {e} | {len(wf)} |\n"
    md += f"\n{count} stories ({state_summary}).\n"

    path = _write_detail(filename, md)
    return f"{count} stories ({state_summary}). → {path}"


def fmt_search(data: list) -> str:
    if isinstance(data, dict) and _is_error(data):
        return _fmt_error(data)
    if not isinstance(data, list):
        return json.dumps(data)

    count = len(data)
    if count == 0:
        return "0 results."

    md = "# Search Results\n\n"
    for item in data:
        rtype = item.get("type", "?")
        rid = item.get("id", "?")
        rtitle = item.get("title", "?")
        md += f"- **{rtype}** {rid}: {rtitle}\n"
    md += f"\n{count} results.\n"

    path = _write_detail("search.md", md)
    return f"{count} results. → {path}"


def fmt_view(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    board = data.get("board", {})
    wip = data.get("wip", {})
    by_state = wip.get("by_state", {})
    epics = data.get("epics", [])
    callouts = data.get("callouts", {})
    scope = data.get("scope", "all")

    # One-liner summary
    total = wip.get("total_active", sum(by_state.values()))
    state_parts = []
    for st in ["draft", "ready", "in-progress", "blocked", "done"]:
        if by_state.get(st, 0) > 0:
            state_parts.append(f"{by_state[st]} {st}")
    summary = ", ".join(state_parts) if state_parts else f"{total} stories"

    # Detail file
    md = f"# Board — {scope}\n\n"

    if epics:
        md += "## Epics\n\n"
        for e in epics:
            eid = e.get("id", "?")
            et = e.get("title", "?")
            prog = e.get("progress", {})
            pct = prog.get("pct_done", 0)
            total_s = prog.get("total", 0)
            md += f"- {eid}: {et} ({pct}% of {total_s})\n"
        md += "\n"

    if board:
        md += "## Board\n\n"
        for state, stories in board.items():
            md += f"### {state} ({len(stories)})\n\n"
            for s in stories:
                sid = s.get("id", "?")
                st = s.get("title", "?")
                a = _abbr_agent(s.get("agent"))
                md += f"- {sid}: {st} [{a}]\n"
            md += "\n"

    blocked_list = callouts.get("blocked", [])
    stale_list = callouts.get("stale", [])
    if blocked_list:
        md += "## Blocked\n\n"
        for b in blocked_list:
            md += f"- {b.get('id', '?')}: {b.get('title', '?')}\n"
        md += "\n"
    if stale_list:
        md += "## Stale\n\n"
        for s in stale_list:
            md += f"- {s.get('id', '?')}: {s.get('title', '?')} (since {s.get('started_at', '?')})\n"
        md += "\n"

    path = _write_detail("view.md", md)
    return f"Board: {summary}. → {path}"


def fmt_roadmap(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    milestones = data.get("milestones", [])
    unordered = data.get("unordered", [])
    summary = data.get("summary", {})
    total = summary.get("total_epics", len(milestones) + len(unordered))
    at_risk = summary.get("at_risk", 0)

    all_epics = milestones + unordered

    md = "# Roadmap\n\n"
    md += "| # | Epic | Title | Target | Progress | Status |\n"
    md += "|---|------|-------|--------|----------|--------|\n"
    for e in all_epics:
        eid = e.get("epic_id", "?")
        t = e.get("title", "?")
        order = e.get("milestone_order")
        order_str = str(order) if order is not None else "—"
        target = e.get("target_date") or "—"
        prog = e.get("progress", {})
        pct = prog.get("pct", 0)
        state = e.get("state", "?")
        risk = " AT-RISK" if e.get("at_risk") else ""
        md += f"| {order_str} | {eid} | {t} | {target} | {pct}% | {state}{risk} |\n"

    md += f"\n{total} epics, {at_risk} at-risk.\n"

    path = _write_detail("roadmap.md", md)
    return f"{total} epics, {at_risk} at-risk. → {path}"


def fmt_plan_story(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    sid = data.get("story_id", "?")
    agent = _abbr_agent(data.get("agent"))
    tasks = data.get("tasks_created", 0)
    wf = data.get("write_files") or []
    title = data.get("title", "?")

    md = f"# Planned: {sid}\n\n"
    md += f'"{title}"\n'
    md += f"Agent: {agent}\n"
    md += f"Tasks created: {tasks}\n"
    if wf:
        md += "\nWrite files:\n"
        for f in wf:
            md += f"- {f}\n"

    path = _write_detail(f"plan-story-{sid.replace('story-', '')}.md", md)
    return f"Planned {sid}: {agent}, {tasks} tasks. → {path}"


def fmt_plan_stories(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    # Simple message (no stories to plan)
    if "message" in data and "stories" not in data:
        return data["message"]

    stories = data.get("stories", [])
    epic_id = data.get("epic_id", "")
    warnings = data.get("warnings", [])
    count = len(stories)

    md = f"# Planned stories\n\n"
    if epic_id:
        md += f"Epic: {epic_id}\n\n"

    md += "| Story | Title | Agent | Tasks | Group | Depends |\n"
    md += "|-------|-------|-------|-------|-------|--------|\n"
    for s in stories:
        sid = s.get("story_id", "?")
        t = s.get("title", "?")
        a = _abbr_agent(s.get("agent"))
        tc = s.get("tasks_created", 0)
        pg = s.get("parallel_group", "—")
        deps = ", ".join(s.get("depends_on", [])) or "—"
        err = s.get("error", "")
        if err:
            md += f"| {sid} | {t} | ERROR | — | — | {err} |\n"
        else:
            md += f"| {sid} | {t} | {a} | {tc} | {pg} | {deps} |\n"

    if warnings:
        md += "\n## Warnings\n\n"
        for w in warnings:
            md += f"- {w}\n"

    md += f"\n{count} stories planned.\n"

    suffix = f"-{epic_id}" if epic_id else ""
    path = _write_detail(f"plan{suffix}.md", md)

    # Count groups for one-liner
    groups = set(s.get("parallel_group", 1) for s in stories if not s.get("error"))
    return f"Planned {count} stories, {len(groups)} groups. → {path}"


def fmt_plan_bulk(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    epics = data.get("epics", [])
    md = f"# Bulk Plan\n\n"
    md += json.dumps(data, indent=2)
    path = _write_detail("plan-bulk.md", md)
    return f"Bulk plan: {len(epics)} epics. → {path}"


def fmt_critique(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    findings = data.get("findings", [])
    story_ids = data.get("story_ids", [])
    blocking = data.get("blocking_count", 0)
    total = data.get("finding_count", len(findings))
    warn = sum(1 for f in findings if f.get("severity") == "warning")
    note = total - blocking - warn

    md = "# Critique\n\n"
    md += f"Stories: {', '.join(story_ids)}\n\n"
    if findings:
        md += "| Severity | Category | Story | Description |\n"
        md += "|----------|----------|-------|-------------|\n"
        for f in findings:
            sev = f.get("severity", "?")
            cat = f.get("category", "?")
            sid = f.get("story_id", "?")
            desc = f.get("description", "?")
            md += f"| {sev} | {cat} | {sid} | {desc} |\n"
    md += f"\n{total} findings ({blocking} blocking, {warn} warning, {note} note).\n"

    # Use first story ID for filename if available
    suffix = f"-{story_ids[0]}" if story_ids else ""
    path = _write_detail(f"critique{suffix}.md", md)
    return f"{total} findings ({blocking} blocking, {warn} warn). → {path}"


def fmt_check_conflicts(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    conflicts = data.get("conflicts", [])
    safe = data.get("safe_parallel", [])
    seq = data.get("sequential", [])

    md = "# Conflict Check\n\n"
    if conflicts:
        md += "## Conflicts\n\n"
        for c in conflicts:
            md += f"- `{c.get('file', '?')}` → {', '.join(c.get('stories', []))}\n"
        md += "\n"
    md += f"Safe parallel: {', '.join(safe) or '(none)'}\n"
    md += f"Sequential: {', '.join(seq) or '(none)'}\n"

    path = _write_detail("conflicts.md", md)
    n = len(conflicts)
    return f"{n} conflict{'s' if n != 1 else ''} found. → {path}"


def fmt_plan_items(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    phase = data.get("phase", "?")

    if phase == "proposal":
        stories = data.get("proposed_stories", [])
        count = data.get("story_count", len(stories))
        pid = data.get("proposal_id", "?")
        md = f"# Plan Items — Proposal {pid}\n\n"
        md += f"Items: {data.get('item_count', '?')}\n\n"
        md += "Proposed stories:\n"
        for i, title in enumerate(stories, 1):
            md += f"{i}. {title}\n"
        md += f"\nCall with confirmed=True and proposal_id='{pid}' to commit.\n"
        path = _write_detail("plan-items.md", md)
        return f"Proposal {pid}: {count} stories. → {path}"

    if phase == "committed":
        ce = data.get("created_epics", [])
        cs = data.get("created_stories", [])
        ct = data.get("created_tasks", [])
        md = "# Plan Items — Committed\n\n"
        md += data.get("summary", "") + "\n\n"
        if ce:
            md += "## Epics\n\n"
            for e in ce:
                md += f"- {e.get('id', '?')}: {e.get('title', '?')}\n"
            md += "\n"
        if cs:
            md += "## Stories\n\n"
            for s in cs:
                md += f"- {s.get('id', '?')}: {s.get('title', '?')} (epic: {s.get('epic_id', '?')})\n"
            md += "\n"
        path = _write_detail("plan-items.md", md)
        return f"Committed: {len(ce)} epics, {len(cs)} stories, {len(ct)} tasks. → {path}"

    return json.dumps(data)


def fmt_reorder(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    stories = data.get("stories", [])
    epic_id = data.get("epic_id", "")
    warnings = data.get("warnings", [])

    md = "# Reorder\n\n"
    if epic_id:
        md += f"Epic: {epic_id}\n\n"
    md += "| # | Story | Title | State |\n|---|-------|-------|-------|\n"
    for s in stories:
        idx = s.get("order_idx", "—")
        sid = s.get("id", "?")
        t = s.get("title", "?")
        st = s.get("state", "?")
        md += f"| {idx} | {sid} | {t} | {st} |\n"
    if warnings:
        md += "\nWarnings:\n"
        for w in warnings:
            md += f"- {w}\n"

    suffix = f"-{epic_id}" if epic_id else ""
    path = _write_detail(f"reorder{suffix}.md", md)
    return f"Reordered: {len(stories)} stories. → {path}"


def fmt_triage(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    backlog = data.get("backlog_stories", [])
    unassigned = data.get("unassigned_stories", [])
    no_tasks = data.get("draft_without_tasks", [])
    moves = data.get("suggested_moves", [])

    md = "# Triage\n\n"

    if backlog:
        md += f"## Backlog ({len(backlog)})\n\n"
        for s in backlog:
            md += f"- {s.get('id', '?')}: {s.get('title', '?')} [{s.get('state', '?')}]\n"
        md += "\n"

    if unassigned:
        md += f"## Unassigned ({len(unassigned)})\n\n"
        for s in unassigned:
            md += f"- {s.get('id', '?')}: {s.get('title', '?')}\n"
        md += "\n"

    if no_tasks:
        md += f"## Draft without tasks ({len(no_tasks)})\n\n"
        for s in no_tasks:
            md += f"- {s.get('id', '?')}: {s.get('title', '?')}\n"
        md += "\n"

    if moves:
        md += f"## Suggested moves ({len(moves)})\n\n"
        for m in moves:
            md += f"- {m.get('story_id', '?')} → {m.get('suggested_epic_id', '?')} (score: {m.get('score', '?')})\n"
        md += "\n"

    path = _write_detail("triage.md", md)
    return f"{len(unassigned)} unassigned, {len(no_tasks)} no-tasks. → {path}"


def fmt_cleanup(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    dry_run = data.get("dry_run", False)
    archived = data.get("would_archive_stories", data.get("archived_stories", []))
    closed = data.get("would_close_epics", data.get("closed_epics", []))
    stale = data.get("stale_stories", [])
    mismatches = data.get("task_mismatches", [])

    mode = "dry run" if dry_run else "applied"

    md = f"# Cleanup ({mode})\n\n"

    if archived:
        label = "Would archive" if dry_run else "Archived"
        md += f"## {label} ({len(archived)})\n\n"
        for s in archived:
            if isinstance(s, dict):
                md += f"- {s.get('id', '?')}: {s.get('title', '?')}\n"
            else:
                md += f"- {s}\n"
        md += "\n"

    if closed:
        label = "Would close" if dry_run else "Closed"
        md += f"## {label} ({len(closed)})\n\n"
        for e in closed:
            if isinstance(e, dict):
                md += f"- {e.get('id', '?')}: {e.get('title', '?')}\n"
            else:
                md += f"- {e}\n"
        md += "\n"

    if stale:
        md += f"## Stale ({len(stale)})\n\n"
        for s in stale:
            md += f"- {s.get('id', '?')}: {s.get('title', '?')} (since {s.get('started_at', '?')})\n"
        md += "\n"

    if mismatches:
        md += f"## Task state mismatches ({len(mismatches)})\n\n"
        for m in mismatches:
            md += f"- {m.get('task_id', '?')} in {m.get('story_id', '?')}: task in-progress but story is {m.get('story_state', '?')}\n"
        md += "\n"

    path = _write_detail("cleanup.md", md)
    a_count = len(archived)
    c_count = len(closed)
    return f"Cleanup ({mode}): {a_count} archived, {c_count} closed. → {path}"


def fmt_regroup(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    phase = data.get("phase", "?")

    if phase == "proposal":
        moves = data.get("moves", [])
        new_epics = data.get("new_epics", [])
        md = "# Regroup — Proposal\n\n"
        if moves:
            md += f"## Moves ({len(moves)})\n\n"
            for m in moves:
                md += f"- {m.get('story_id', '?')}: {m.get('from_epic', '?')} → {m.get('to_epic', '?')} ({m.get('to_epic_title', '')})\n"
            md += "\n"
        if new_epics:
            md += f"## New epics ({len(new_epics)})\n\n"
            for ne in new_epics:
                md += f"- {ne.get('title', '?')} ({len(ne.get('story_ids', []))} stories)\n"
            md += "\n"
        path = _write_detail("regroup.md", md)
        affected = len(set(m.get("to_epic", "") for m in moves))
        return f"Regroup proposal: {len(moves)} moves, {len(new_epics)} new epics. → {path}"

    if phase == "committed":
        moved = data.get("moved", [])
        created = data.get("created_epics", [])
        skipped = data.get("skipped", [])
        md = "# Regroup — Committed\n\n"
        md += f"Moved: {len(moved)}, Created epics: {len(created)}, Skipped: {len(skipped)}\n\n"
        if moved:
            for m in moved:
                md += f"- {m.get('story_id', '?')} → {m.get('to_epic', '?')}\n"
        path = _write_detail("regroup.md", md)
        return f"Regrouped: {len(moved)} moved, {len(created)} new epics. → {path}"

    return json.dumps(data)


def fmt_cycle_time(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    stories = data.get("stories", [])
    count = data.get("count", len(stories))
    avg = data.get("average_cycle_hours", 0)

    md = "# Cycle Time\n\n"
    if stories:
        md += "| Story | Title | Started | Completed | Hours |\n"
        md += "|-------|-------|---------|-----------|-------|\n"
        for s in stories:
            sid = s.get("id", "?")
            t = s.get("title", "?")
            started = s.get("started_at", "?")
            completed = s.get("completed_at", "?")
            hours = s.get("cycle_hours", "?")
            md += f"| {sid} | {t} | {started} | {completed} | {hours} |\n"
    md += f"\nAvg: {avg}h across {count} stories.\n"

    path = _write_detail("cycle-time.md", md)
    return f"Avg {avg}h across {count} stories. → {path}"


def fmt_throughput(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    items = data.get("data", [])
    avg = data.get("average_per_period", 0)
    period = data.get("period_type", "week")

    md = "# Throughput\n\n"
    md += f"Period: {period}\n\n"
    if items:
        md += "| Period | Completed |\n|--------|-----------|\n"
        for item in items:
            md += f"| {item.get('period', '?')} | {item.get('completed', 0)} |\n"
    md += f"\nAvg: {avg} stories/{period}.\n"

    path = _write_detail("throughput.md", md)
    return f"{avg} stories/{period}. → {path}"


def fmt_wip(data: dict) -> str:
    if _is_error(data):
        return _fmt_error(data)

    wip = data.get("wip", {})
    blocked = data.get("blocked", [])
    ct = data.get("cycle_time", {})
    tp = data.get("throughput", {})
    total = wip.get("total_active", 0)
    by_state = wip.get("by_state", {})
    ip = by_state.get("in-progress", 0)

    md = "# WIP Health\n\n"
    md += f"Total active: {total}\n\n"

    if by_state:
        md += "## By state\n\n"
        for st, cnt in sorted(by_state.items()):
            md += f"- {st}: {cnt}\n"
        md += "\n"

    by_agent = wip.get("by_agent", {})
    if by_agent:
        md += "## By agent\n\n"
        for ag, cnt in sorted(by_agent.items()):
            md += f"- {ag}: {cnt}\n"
        md += "\n"

    if blocked:
        md += f"## Blocked ({len(blocked)})\n\n"
        for b in blocked:
            md += f"- {b.get('id', '?')}: {b.get('title', '?')}\n"
        md += "\n"

    avg_ct = ct.get("average_hours", 0)
    avg_tp = tp.get("average_per_week", 0)
    trend = tp.get("trend", "stable")
    md += f"Cycle time: {avg_ct}h avg\n"
    md += f"Throughput: {avg_tp}/week ({trend})\n"

    path = _write_detail("wip.md", md)
    return f"WIP: {ip}/{total}, {len(blocked)} blocked. → {path}"


def fmt_analyze(text: str) -> str:
    """Format analyze response — receives raw text, not a dict."""
    if not text or text.startswith("[gemini error") or text.startswith("[gemini parse error"):
        return text

    # Extract verdict from text
    verdict = "UNKNOWN"
    for v in ("APPROVE", "NEEDS CHANGES", "REJECT", "PROCEED", "REVISE", "RECONSIDER"):
        if v in text[:500]:
            verdict = v
            break

    # Count findings (look for numbered items or bullet points after verdict)
    lines = text.strip().splitlines()
    finding_count = sum(1 for line in lines if line.strip().startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.")))

    path = _write_detail("analyze.md", text)
    return f"Verdict: {verdict} ({finding_count} findings). → {path}"


def fmt_design(text: str, component_name: str) -> str:
    """Format design spec response — writes detail file, returns one-liner."""
    if not text or text.startswith("[gemini error") or text.startswith("[gemini parse error"):
        return text

    import re

    section_count = text.count("\n## ") + (1 if text.startswith("## ") else 0)

    framework = "unknown"
    header = text[:500]
    for fw in ("Flutter", "React", "Vue"):
        if fw in header:
            framework = fw
            break

    sanitized = re.sub(r"[^a-z0-9]+", "-", component_name.lower()).strip("-")
    filename = f"design-{sanitized}.md"
    path = _write_detail(filename, text)
    return f"Design spec for {component_name}: {section_count} sections, {framework}. -> {path}"
