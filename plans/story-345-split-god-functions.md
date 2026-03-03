# Story 345 — Split god functions into focused single-purpose tools

## Goal
Replace multi-mode tools (pm_plan, pm_housekeep, pm_view) with focused single-purpose tools. Each mode becomes its own registered MCP tool with clear parameters.

## Changes

### 1. `tools_pm_plan.py` — Split pm_plan into 3 tools

**Current**: `pm_plan(epic_id, story_id, story_ids, ...)` with 4 modes selected by which parameter is set.

**New tools:**
- `pm_plan_story(story_id, paths, project_root, context)` — single story mode
- `pm_plan_stories(story_ids, stories, paths, project_root, context)` — multi-story + epic mode (keep epic_id as optional scope filter)
- `pm_plan_bulk(paths, project_root, context)` — bulk roadmap mode

Keep `pm_plan` as a thin dispatcher for backwards compat (calls the right sub-tool based on args). This avoids breaking existing skill references.

Actually, simpler approach: **don't keep the dispatcher**. Just split into the 3 tools and update skill references. The MCP tool descriptions are auto-discovered by Claude Code.

**Implementation:**
- Extract story mode body (lines 57-109) into `pm_plan_story`
- Extract multi-story mode body (lines 112-192) into `pm_plan_stories`, add `epic_id` param that fetches draft stories
- Extract bulk mode body (lines 258-308) into `pm_plan_bulk`
- Remove the old `pm_plan` registration
- `pm_critique` and `pm_check_conflicts` stay as-is (already focused)

### 2. `tools_pm_organize.py` — Split pm_housekeep into 3 tools

**Current**: `pm_housekeep(mode, ...)` with 3 modes: triage, cleanup, regroup.

**New tools:**
- `pm_triage(epic_id)` — find unorganized/backlog work
- `pm_cleanup(archive_days, stale_days, confirmed)` — archive old stories, close empty epics
- `pm_regroup(epic_id, confirmed, proposal)` — re-cluster stories across epics

**Implementation:**
- Extract triage body (lines 146-207) into `pm_triage`
- Extract cleanup body (lines 210-288) into `pm_cleanup`
- Extract regroup body (lines 291-436) into `pm_regroup`
- Remove the old `pm_housekeep` registration
- `pm_reorder` stays as-is (already focused)

### 3. `tools_pm_read.py` — Split pm_view into 2 tools

**Current**: `pm_view(epic_id, detail, include_archived)` with 3 detail levels.

**New tools:**
- `pm_board(epic_id)` — kanban board + WIP + callouts (was detail="board")
- `pm_dashboard(epic_id, include_archived)` — epic summaries with progress (was detail="summary"), plus optional board/callouts
- Actually: keep `pm_view` as-is with its `detail` parameter. It's already well-structured and the detail parameter is ergonomic. Instead of splitting, just rename for clarity if needed.

**Revised approach**: `pm_view` is actually fine. Its `detail` parameter acts as a progressive disclosure mechanism, not a mode switch. All 3 levels share the same base query. Don't split this one — it would increase duplication without improving clarity.

Skip task t3 (pm_view split). Mark it as "skipped" with reason.

### 4. `tools_pm_analytics.py` — Split pm_metrics into 3 tools

**Current**: `pm_metrics(metric, ...)` with 3 metrics: cycle_time, throughput, health.

**New tools:**
- `pm_cycle_time(epic_id, since)` — cycle time analysis
- `pm_throughput(epic_id, period, lookback)` — throughput over time
- `pm_wip(epic_id)` — WIP health (replaces old pm_wip that was already in MCP descriptions)

**Implementation:**
- Extract cycle_time body into `pm_cycle_time`
- Extract throughput body into `pm_throughput`
- Extract health body into `pm_wip`
- Remove old `pm_metrics`

### 5. Skill updates

- `skills/cleanup/SKILL.md`: `pm_housekeep(mode="cleanup")` → `pm_cleanup()`
- `skills/run-stories/SKILL.md`: `pm_view(detail="summary")` → `pm_view(detail="summary")` (no change, keeping pm_view)

### 6. Server registration

No changes needed to `server.py` — the `register(mcp)` pattern is per-module, and each module registers its own tools. The module-level registration stays the same.

## Validation
- `python3 -c "import server"` succeeds
- Each new tool name appears in the MCP tool list
- Old multi-mode tool names (`pm_plan`, `pm_housekeep`, `pm_metrics`) no longer appear
- Skills reference correct tool names
