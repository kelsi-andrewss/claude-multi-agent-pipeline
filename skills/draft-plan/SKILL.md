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
Gemini is the researcher. You are the critic. Exploration happens only during your post-Gemini critique. Read `refs/orch-critique-checklist.md` for the full 10-point checklist before writing each plan file.

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

**Gather past failure context:**
Before launching the planner agent, query `~/.claude/.claude/run-state.db`:
```bash
sqlite3 -separator "\t" ~/.claude/.claude/run-state.db \
  "SELECT story_id, what_failed FROM merge_outcomes WHERE what_failed != 'nothing' AND what_failed != '' ORDER BY created_at DESC LIMIT 10;"
```
If the DB file is missing, skip this step. Build a `PAST_FAILURES` block with format:
```
PAST_FAILURES:
  story-NNN (agent, model): <what failed>
  story-NNN (agent, model): <what failed>
```
Include this block in the planner agent prompt (Step 2 agent call below) so Gemini has context about recurring failure modes.

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

<PAST_FAILURES block if any failures were extracted, omit section if none>
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

## Step 5: Write plan files (background agents)

Plan files are written by background agents to preserve main-session context.

### Step 5a: Prepare plan-writer launches

1. Read `refs/orch-critique-checklist.md` once (keep its content for the agent prompts).
2. Glob `plans/*.md` once to get existing names. For each story, generate a unique `<adjective>-<noun>` plan file name not already in use.

### Step 5b: Launch plan-writer agents

**For fast-path stories:** Write plan files directly in the main session (no agent needed — metadata-only, no file reads):
```
## Context
story-NNN: <title>
Files: <write_files>

## What changes
- <task 1 description>
- <task 2 description>

## Verification criteria
- <one testable statement per task, derived from task description>

## Verification
- Confirm each task is implemented correctly
- No changes outside write scope
```

No `## Contract` section for fast-path stories — they are small, single-agent, no test agent involvement.

**For Gemini-planned stories:** Launch one `general-purpose` background agent per story with `run_in_background: true`. Use this prompt template:

```
You are writing a plan file for story <story_id>: "<title>"

Agent: <agent>
Tasks: <task list from pm_get_story>
Write files: <write_files list>
Read files: <read_files list>
Output file: plans/<name>.md

## Predicted Preferences
<For each story, before launching the agent, call pm_predict_preference(domain=<domain>) where domain
is inferred from write_files: "hooks" for hook files, "tracking" for tracking files, "skills" for
skill files, "refs" for refs files, etc. If predictions are returned, include them here:>
  - <domain>: <preference text> (confidence: <score>)
<If no predictions returned, omit this section entirely.>

## Critique Checklist
<full checklist content from refs/orch-critique-checklist.md>

## Instructions

1. Read the story's write_files to understand what exists today.
2. Read files referenced by tasks but not in write_files — these become read-only context. Identify all new or modified public interfaces from write_files.
3. Apply the critique checklist against the Gemini-planned tasks:
   - If SIGNIFICANT issues found (missing files, scope creep, convention violations):
     Return: "NEED_DECISION: <issue>\nOption A: <fix>\nOption B: <fix>"
   - If MINOR gaps (edge cases, existing utilities): incorporate silently.
3.5. Extract function/class signatures for every new or modified public interface found in step 2. Write the `## Contract` section with signatures in the format: `functionName(param: Type, param2: Type) -> ReturnType` — one-line purpose. Include import paths for shared interfaces that the test agent needs.
3.6. Convert Gemini tasks into testable acceptance criteria (given/when/then or equivalent). Each criterion should map to at least one task. If the story has `test_files`, each criterion must reference the specific test file that will verify it. Write the `## Acceptance criteria` section.
4. Write the plan file to plans/<name>.md with this structure:

   ## Context
   <what this story is about, which files are affected>

   ## What changes
   <bulleted list of specific changes, one per task>

   ## Contract
   <for each new/modified public function or class>
   - `functionName(param: Type, param2: Type) -> ReturnType` — one-line purpose
   - `ClassName` — purpose
     - `method(param: Type) -> ReturnType`
   <import paths for shared interfaces that test agent needs>

   ## Acceptance criteria
   - Given <precondition>, when <action>, then <expected outcome>
   - Given <precondition>, when <action>, then <expected outcome>
   <each criterion references the test file that will verify it, if test_files exist>

   ## Verification
   <how to verify the implementation is correct>

5. Return: "DONE: plans/<name>.md"
```

### Step 5c: Critique loop

After all plan files are written (both fast-path and agent-written), run the critique loop on each:

1. For each plan file, apply the critique logic (Steps 3–4 from `/critique` SKILL.md):
   - Self-critique: 2 passes max, 5 core questions, NMIP gating per question.
   - Gemini escalation: use `mcp__gemini__pm_critique` (story IDs are available).
   - Fix improvements inline in the plan files.
2. Mandatory even for fast-path stories.
3. Store learnings per `/critique` Step 5 (tool-learning tag, blind spots if Gemini caught NMIP'd items).
4. Do NOT append `## Self-critique` sections to plan files — note findings in the Step 6 report instead.

**Contract gate** (Gemini-planned stories only, skip for fast-path):

After self-critique passes and before Gemini escalation, run this structural validation:

- If `test_files` exist on the story AND `## Contract` section is missing or empty: reject. Return to plan-writer agent with: "Plan rejected: missing ## Contract section. Story has test_files — test agent needs function signatures to write tests. Extract signatures from write_files and add ## Contract."
- If `## Acceptance criteria` section is missing or contains fewer criteria than tasks: reject. Return with: "Plan rejected: missing or insufficient ## Acceptance criteria. Each task needs at least one testable criterion."
- Stories without `test_files`: contract section is recommended but not gating. Acceptance criteria still required (minimum 1 per story).

This is a structural check — presence and count, not quality.

### Step 5d: Collect results and update DB

Wait for all background agents to complete. For each result:

- `DONE: plans/<name>.md` — Load `ToolSearch: select:mcp__gemini__pm_update_story`, then call `pm_update_story(story_id=<id>, plan_file="plans/<name>.md")`.
- `NEED_DECISION: <issue>` — Surface to user, get answer, resume agent.
- `BLOCKED: <reason>` — Report to user, skip story.

Also call `pm_update_story` for each fast-path story written in the main session.

### Step 5e: Cleanup

Delete any source `.md` files (from the file path list in Step 1) using `Bash: rm <path>`.

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
