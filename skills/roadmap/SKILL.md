---
name: roadmap
description: >
  Bird's-eye roadmap view with milestone progress, at-risk detection, and quick
  actions (check-off, archive, add, target, reorder, health). Use when the user
  says "/roadmap", "/roadmap check story-NNN", "/roadmap archive story-NNN",
  "/roadmap add 'Title'", "/roadmap target epic-NNN YYYY-MM-DD",
  "/roadmap reorder", or "/roadmap health".
triggers:
  - /roadmap
  - /roadmap check
  - /roadmap archive
  - /roadmap add
  - /roadmap target
  - /roadmap reorder
  - /roadmap health
---

# Roadmap Skill Invoked

User has requested: `/roadmap {{args}}`

---

## Step 0: Load tools

```
ToolSearch: select:mcp__gemini__pm_roadmap
ToolSearch: select:mcp__gemini__pm_update_story
ToolSearch: select:mcp__gemini__pm_update_epic
ToolSearch: select:mcp__gemini__pm_create_epic
ToolSearch: select:mcp__gemini__pm_wip
```

---

## Step 1: Parse args

Inspect `{{args}}` (trim whitespace). Match the first token:

- **Empty or whitespace** -> Default view mode
- `check story-NNN` -> Check-off mode
- `archive story-NNN` -> Archive mode
- `add "Title"` or `add Title` -> Add milestone mode
- `target epic-NNN YYYY-MM-DD` -> Set target date mode
- `reorder` -> Reorder mode
- `health` -> Health mode

---

## Default view (no subcommand)

1. Call `pm_roadmap()`.
2. Format the output as a table:

```
Roadmap (N epics: X on-track, Y at-risk, Z completed)

#  Epic           Target      Progress         Status
1  Auth Rewrite   2026-03-15  ████████░░ 80%   on-track
2  PM Redesign    2026-03-20  ███░░░░░░░ 30%   AT-RISK
-  Backlog        -           ██░░░░░░░░ 20%   active
```

Milestones (with `milestone_order`) appear first, sorted by order.
Unordered epics appear below a separator, sorted by ID.
Use 10-char progress bars.

---

## check story-NNN

1. Call `pm_update_story(story_id="story-NNN", state="done")`.
2. Print: `story-NNN marked done.`
3. Call `pm_roadmap()` and display the updated table.

---

## archive story-NNN

1. Call `pm_update_story(story_id="story-NNN", archived=True)`.
2. Print: `story-NNN archived.`
3. Call `pm_roadmap()` and display the updated table.

---

## add "Title"

1. Determine the next milestone_order: call `pm_roadmap()`, read the detail file to find the max `milestone_order` among milestones, add 1.
2. Call `pm_create_epic(title="Title", milestone_order=<next>)`.
3. Print: `Created epic-NNN: "Title" (milestone #N).`
4. Display the updated roadmap table.

---

## target epic-NNN YYYY-MM-DD

1. Call `pm_update_epic(epic_id="epic-NNN", target_date="YYYY-MM-DD")`.
2. Print: `epic-NNN target set to YYYY-MM-DD.`
3. Call `pm_roadmap()` and display the updated table.

---

## reorder

1. Call `pm_roadmap()` and read the detail file.
2. Display current milestone order as a numbered list.
3. Use `AskUserQuestion` to ask: "Enter the new order as a comma-separated list of epic IDs (e.g., epic-22, epic-25, epic-23)."
4. Parse the response, then call `pm_update_epic(epic_id=..., milestone_order=N)` for each, where N = 1, 2, 3...
5. Display the updated roadmap table.

---

## health

1. Call `pm_wip()` and `pm_roadmap()` in parallel.
2. Display a combined view:

```
Project Health

WIP: N active stories (X in-progress, Y blocked, Z draft)
Agents: quick-fixer: A, architect: B, unassigned: C
Avg cycle time: N.N hours (M stories)
Throughput: N.N stories/week (trend: improving/stable/declining)
Blocked: story-NNN "title", story-MMM "title"

Roadmap:
<roadmap table from default view>
```
