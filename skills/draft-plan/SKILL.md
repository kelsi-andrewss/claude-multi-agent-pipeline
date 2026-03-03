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

## CRITICAL: Do not explore the codebase before calling Gemini.
Your first action is ALWAYS to call Gemini (`pm_plan_story`, `pm_plan_stories`, or `pm_plan_items`) with the user's intent.
Do NOT read source files, run Glob/Grep, or enter plan mode before Gemini returns its output.
Gemini is the researcher. You are the critic. Exploration happens only during your post-Gemini critique (§6 of ORCHESTRATION.md).

---

Run Gemini planning (`pm_plan_story`/`pm_plan_stories`) on the target stories/epic, then immediately convert
the Gemini output into Claude-style plan files (`plans/<whimsical-name>.md`) and store
the filename back in the DB via `pm_update_story`.

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
ToolSearch: select:mcp__gemini__pm_plan_story
ToolSearch: select:mcp__gemini__pm_plan_stories
ToolSearch: select:mcp__gemini__pm_list_stories
ToolSearch: select:mcp__gemini__pm_get_story
ToolSearch: select:mcp__gemini__pm_check_conflicts
ToolSearch: select:mcp__gemini__pm_critique
```

**For file paths** (`.md`):
- Read the file and search for `story-\d+`.
- If a story ID is found, add it to the story list and run `pm_plan_story(story_id=...)` for it (skip grouping below for these).
- If no story ID found, ask the user: "Could not find a story ID in `<path>`. Which story does this plan belong to?"

**For explicit epic IDs** (from Step 1): call `pm_plan_stories(epic_id=<id>)` directly — no grouping check needed.

**For story IDs** — use epic-grouped planning where safe:

1. **Fetch epic membership** (parallel): call `pm_get_story(story_id=<id>)` for each story ID to get its `epic_id`. Do all in a single message.

2. **Group stories by epic_id.**

3. **Determine call mode per epic** (parallel): for each unique epic, call `pm_list_stories(epic_id=<id>)` to get all non-archived stories in that epic. Do all in a single message.

4. **Decide per epic**:
   - If **all** `draft`/`ready` stories in the epic are in the target list → use epic mode: `pm_plan_stories(epic_id=<id>)`
   - Otherwise → fall back to multi-story mode: `pm_plan_stories(story_ids=[<id>, ...])`  with all targeted stories from that epic in one call

5. **Call `pm_plan_story`/`pm_plan_stories` in a single message** (parallel tool calls) — one call per epic in epic mode, one `story_ids` call per partial-epic group in multi-story mode. Include any file-path stories and explicit epic IDs from above.

Wait for **all** calls to complete before proceeding.

After all planning calls complete, resolve the full concrete story list:

- Story IDs: already resolved.
- Epic IDs (explicit from Step 1): call `pm_list_stories(epic_id=...)`, filter to non-archived, add to story list.

Deduplicate. If the story list is empty, stop and report: "No stories found. Nothing to plan."

---

## Step 3: Verify plan data exists

For each story in the final list:
- Call `pm_get_story(story_id)`.
- If the output contains no agent assignment and no tasks, warn: "story-NNN: planning returned no data — skipping." and remove from list.

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

Load `ToolSearch: select:mcp__gemini__pm_update_story`.

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
   Content comes from the `pm_get_story` output collected in Step 3.

3. **Call `pm_update_story` for all stories in a single message** (parallel tool calls):
   - `pm_update_story("<story_id>", plan_file="plans/<whimsical-name>.md")` for each

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

## Step 7: Run

Call `pm_check_conflicts(story_ids=[...all story IDs...])` to check for write-target overlaps.

**If `conflicts` is empty** (no overlaps), output a summary and immediately invoke `/run-stories`:

```
Running N stories:
  story-NNN — <title> — <agent> — plan: plans/<file>.md
  ...
```

Then invoke `/run-stories <all-story-ids>`.

**If `conflicts` is non-empty**, output the conflict summary first:

```
Conflict: story-238 and story-240 both write <file-path>
```

List one line per conflict pair. Then:
- Invoke `/run-stories` with the `safe_parallel` set immediately.
- Note which `sequential` stories to run after merge: "Run story-240 after story-238 merges."

Use "run X after Y merges" (not "skip X until Y merges") when describing deferred stories.
