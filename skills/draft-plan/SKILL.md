---
name: draft-plan
description: >
  Run Gemini planning on a story/epic, then immediately convert the result into
  Claude-style plan files. Use when the user says "/draft-plan", "plan this story",
  "ask gemini to plan story-NNN", "plan epic-NNN", or any natural-language request
  to plan a story or epic.
triggers:
  - /draft-plan
  - /draft-plan story-NNN
  - /draft-plan epic-NNN
  - /draft-plan plans/some-file.md
  - plan this story
  - ask gemini to plan
---

Run Gemini planning (`pm_plan`) on the target stories/epic, then immediately convert
the Gemini output into Claude-style plan files (`plans/<whimsical-name>.md`) and store
the filename back in the DB via `pm_set_plan_file`.

## Args

`{{args}}` — zero or more space-separated tokens. Each token is one of:
- `story-\d+` → a story ID
- `epic-\d+` → an epic ID (expand to all non-archived stories)
- a path ending in `.md` → a file path to an existing Gemini plan file
- (no args) → ask the user which story or epic to plan

---

## Step 1: Parse args

Classify each token in `{{args}}`:

- Matches `story-\d+` → add to story ID list
- Matches `epic-\d+` → add to epic ID list
- Ends with `.md` → add to file path list
- No args at all → use `AskUserQuestion` to ask: "Which story or epic should I plan?" and stop until the user responds

---

## Step 2: Run Gemini planning

Load the Gemini MCP tools:

```
ToolSearch: select:mcp__gemini__pm_plan
ToolSearch: select:mcp__gemini__pm_list_stories
ToolSearch: select:mcp__gemini__pm_plan_view
```

Call `pm_plan` for **all story IDs and epic IDs in a single message** (parallel tool calls):
- Stories: `pm_plan(story_id=<id>)` for each
- Epics: `pm_plan(epic_id=<id>)` for each

Wait for **all** calls to complete before proceeding.

**For file paths** (`.md`):
- Read the file and search for `story-\d+`.
- If a story ID is found, add it to the story list and run `pm_plan(story_id=...)` for it.
- If no story ID found, ask the user: "Could not find a story ID in `<path>`. Which story does this plan belong to?"

After all `pm_plan` calls complete, resolve the full concrete story list:

- Story IDs: already resolved.
- Epic IDs: call `pm_list_stories(epic_id=...)`, filter to non-archived, add to story list.

Deduplicate. If the story list is empty, stop and report: "No stories found. Nothing to plan."

---

## Step 3: Verify plan data exists

For each story in the final list:
- Call `pm_plan_view(story_id)`.
- If the output contains no agent assignment and no tasks, warn: "story-NNN: pm_plan returned no data — skipping." and remove from list.

If the list is empty after filtering, stop and report: "No stories with plan data. Nothing to convert."

---

## Step 4: Ask clarifying questions (if needed)

For each story that is missing any of the following, collect them now in a single `AskUserQuestion` call (group all stories together — do not ask one story at a time):

- **Agent type** — which agent type should handle this story? (`quick-fixer`, `architect`, `manual`)
- **needs_review / needs_testing** — should this story require review or testing before merge?
- **Sections to emphasize** — any special sections or constraints to highlight in the plan?

Skip this step entirely if all stories already have agent assignments and the user has not indicated preferences.

---

## Step 5: Write plan files inline

Load `ToolSearch: select:mcp__gemini__pm_set_plan_file`.

Do all of the following **in the main session** (no background agents):

1. **Generate unique whimsical names**: Glob `plans/*.md` once to get existing names. For each story, pick a unique `<adjective>-<noun>` name not already in use.

2. **Write all plan files in a single message** (parallel `Write` tool calls), one per story:

   Each file at `plans/<whimsical-name>.md` uses this format:
   ```
   ## Context
   <what this story is about, which files are affected>

   ## What changes
   <bulleted list of specific changes, one per task>

   ## Verification
   <how to verify the implementation is correct>
   ```
   Content comes from the `pm_plan_view` output collected in Step 3.

3. **Call `pm_set_plan_file` for all stories in a single message** (parallel tool calls):
   - `pm_set_plan_file("<story_id>", "plans/<whimsical-name>.md")` for each

4. **Delete any source `.md` files** (from the file path list in Step 1) using `Bash: rm <path>`.

---

## Step 6: Report results

Summarize:

```
Planning complete.

story-001 → plans/sparkling-lantern.md
story-002 → plans/noble-harbor.md
story-003 → plans/cosmic-turtle.md
```

If any agent failed or returned an error, list it under an "Errors:" section.

---

## Step 7: What's next?

Use `AskUserQuestion` to ask:

> "Planning complete for N stories. What would you like to do next?"

Options:
- "Run these stories now" → immediately invoke `/run-stories <story-ids>`
- "Add more items to the queue" → invoke `/todo` so the user can queue more work
- "Done for now" → stop
