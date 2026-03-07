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

## CRITICAL: Gemini-first planning (unless fast-path applies)

Before calling Gemini, check each story for fast-path eligibility:
- `agent` = `quick-fixer`
- `write_files` count ≤ 2
- No file in `write_files` appears in the project's protected-files list
- `pm_get_story` returns at least one task

Fast-path stories: skip Gemini entirely. Write their plan files directly in Step 5 using DB metadata only.
All other stories: call Gemini as usual. Do NOT explore the codebase before Gemini returns its output.
Gemini is the researcher. You are the critic. Exploration happens only during your post-Gemini critique. Read `refs/orch-critique-checklist.md` for the full 8-point checklist before writing each plan file.

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

## Step 2: Run planning

**Partition stories:**
1. Call `pm_get_story(story_id)` for each story (parallel, single message). Read each detail file for full story data.
2. Check fast-path criteria for each: agent = `quick-fixer`, write_files count ≤ 2, no protected files, at least one task.
3. Split into `fast_path` and `gemini_path` lists.
4. `fast_path` stories skip directly to Step 5.

**For file paths** (`.md`):
- Read the file and search for `story-\d+`.
- If a story ID is found, add it to the story list and include in `gemini_path`.
- If no story ID found, ask the user: "Could not find a story ID in `<path>`. Which story does this plan belong to?"

**For `gemini_path` stories — delegate to planner agent (foreground):**

```
Agent(subagent_type="planner", prompt="""
MODE: draft-plan
STORY_IDS: [<gemini_path story IDs>]
EPIC_IDS: [<explicit epic IDs from Step 1>]
""")
```

Wait for the planner to return.

**On PLANNER_RESULT**: Extract story metadata (IDs, titles, agents, detail_file paths). Proceed to Step 3.

**On PLANNER_ERROR**: Surface the error to the user with full details (step, tool, error message, partial results). Do NOT fall back to direct MCP calls. Let the user decide: retry, adjust input, or abort.

After planning completes, resolve the full concrete story list (combine fast_path + planner results). Deduplicate. If the story list is empty, stop and report: "No stories found. Nothing to plan."

---

## Step 3: Verify plan data exists

For each story in the final list:
- Call `pm_get_story(story_id)` and read the detail file.
- If the detail file contains no agent assignment and no tasks, warn: "story-NNN: planning returned no data — skipping." and remove from list.

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

   **For fast-path stories:**
   Write plan file using story metadata directly:
   ```
   ## Context
   story-NNN: <title>
   Files: <write_files>

   ## What changes
   - <task 1 description>
   - <task 2 description>

   ## Verification
   - Confirm each task is implemented correctly
   - No changes outside write scope
   ```

   **For Gemini-planned stories:**
   Each file at `plans/<whimsical-name>.md` uses this format:
   ```
   ## Context
   <what this story is about, which files are affected>

   ## What changes
   <bulleted list of specific changes, one per task>

   ## Verification
   <how to verify the implementation is correct>
   ```
   Content comes from the `pm_get_story` detail files collected in Step 3.

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
