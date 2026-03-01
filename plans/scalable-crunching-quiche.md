# Context

The `/draft-plan` → `/run-stories` flow is confusing: two separate commands, no guidance between them, and `pm_plan` calls run sequentially even when operating on different stories. This plan improves the flow with three changes:

1. **Parallelize `pm_plan` calls** in `/draft-plan` — all stories planned in one message
2. **Post-plan interactive prompt** — after planning completes, ask the user what to do next (run stories, add more items, or done)
3. **Auto-chain in `/run-stories`** — if a story has no `plan_file`, auto-call `pm_plan` + write the plan before executing it

---

## Files to Modify

### 1. `skills/draft-plan/SKILL.md`

**Step 2: Parallelize `pm_plan` calls**

Replace the sequential "for each story... wait" pattern with:

> Call `pm_plan` for **all stories and epics in a single message** (parallel tool calls). Wait for all to complete before proceeding.

Current lines 52–58:
```
**For each story ID** in the story list:
- Call `pm_plan(story_id=<id>)`.
- Wait for it to complete before proceeding (it writes tasks, agent, and write_files to DB).

**For each epic ID** in the epic list:
- Call `pm_plan(epic_id=<id>)`.
- Wait for it to complete.
```

Replace with:
```
Call `pm_plan` for **all story IDs and epic IDs in a single message** (parallel tool calls):
- Stories: `pm_plan(story_id=<id>)` for each
- Epics: `pm_plan(epic_id=<id>)` for each

Wait for **all** calls to complete before proceeding.
```

**Add new Step 7: Post-plan interactive prompt**

After the existing Step 6 (report results), add:

```md
## Step 7: What's next?

Use `AskUserQuestion` to ask:

> "Planning complete for N stories. What would you like to do next?"

Options:
- "Run these stories now" → immediately invoke `/run-stories <story-ids>`
- "Add more items to the queue" → invoke `/todo` so the user can queue more work
- "Done for now" → stop
```

---

### 2. `skills/run-stories/SKILL.md`

**Step 1: Auto-plan unplanned stories**

After collecting the story list and before the existing validation skip logic, add an auto-planning step for stories missing `plan_file`:

Current skip logic (line 33):
```
- `plan_file` is null or empty — warn: "story-NNN has no plan file — run `/draft-plan` first"
```

Replace with:
```
- `plan_file` is null or empty:
  - Load `ToolSearch: select:mcp__gemini__pm_plan` and call `pm_plan(story_id=<id>)` for all unplanned stories **in parallel** (single message).
  - Wait for all `pm_plan` calls to complete.
  - Launch one background `general-purpose` agent per unplanned story to write the plan file (same prompt as draft-plan Step 5).
  - Wait for all agents to complete, then re-fetch each story to confirm `plan_file` is now set.
  - If still missing after auto-planning, skip with warning: "story-NNN: auto-planning failed — skipping."
```

---

## Why `pm_plan` Parallel Is Safe

- Each call opens its own SQLite connection; WAL mode serializes writes at the DB level
- Task ID race (`MAX(id)+1`) only matters if two calls target the *same* story simultaneously — impossible here since each call targets a different story
- Temp files are unique per call (`mktemp`)

---

## Verification

1. Run `/draft-plan epic-NNN` with 4+ stories — confirm all `pm_plan` calls fire in one message
2. Confirm post-plan prompt appears with the three options
3. Select "Run these stories now" — confirm `/run-stories` is invoked automatically
4. Run `/run-stories story-NNN` on a story with no `plan_file` — confirm it auto-plans before executing
5. Select "Add more items" — confirm `/todo` is invoked
