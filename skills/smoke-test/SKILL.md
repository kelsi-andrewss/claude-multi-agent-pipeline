---
name: smoke-test
description: >
  Pipeline validation via throwaway artifacts. Creates a smoke-test epic with
  simple stories, runs Gemini planning + plan-writer agents, validates output
  structure and DB state, tears down, and reports pass/fail. Use when the user
  says "/smoke-test ship" or "/smoke-test <mode>".
args:
  - name: args
    type: string
    description: >
      Test mode to run. Currently supported: "ship". Future modes may include
      "coder", "merge", etc.
---

# Smoke Test Skill Invoked

User has requested: `/smoke-test {{args}}`

---

## Step 0: Parse args and validate mode

Inspect `{{args}}` (trim whitespace):

- **Empty or unrecognized** — Print available modes and stop:
  ```
  Usage: /smoke-test <mode>

  Available modes:
    ship — Validates the plan-writer pipeline (epic creation, Gemini planning,
           plan-writer agents, plan file structure, DB state, teardown)
  ```

- **"ship"** — Proceed to Step 1.

---

## Step 1: Create throwaway epic

Load `ToolSearch: select:mcp__gemini__pm_create_epic`.

Call `pm_create_epic(title="[SMOKE TEST] Pipeline validation")`.

Record the returned `epic_id`. The `[SMOKE TEST]` prefix makes it visually distinct in `/roadmap` output and identifiable if teardown fails.

---

## Step 2: Create test stories

Load `ToolSearch: select:mcp__gemini__pm_create_story`.

Create 3 stories under the smoke-test epic. Each targets real existing files that plan-writers can read but that will not actually be modified:

**Story A — quick-fixer path:**
```
pm_create_story(
  title="[SMOKE] Add header comment to smoke-test skill",
  epic_id=<epic_id>,
  write_files=["skills/smoke-test/SKILL.md"],
  agent="quick-fixer",
  tasks=["Add a comment block to the top of skills/smoke-test/SKILL.md describing its purpose"]
)
```

**Story B — architect path:**
```
pm_create_story(
  title="[SMOKE] Add validation notes to critique checklist",
  epic_id=<epic_id>,
  write_files=["refs/orch-critique-checklist.md"],
  agent="architect",
  tasks=[
    "Add a 'Validation notes' section to refs/orch-critique-checklist.md",
    "Include a cross-reference to the smoke-test skill"
  ]
)
```

**Story C — multi-file architect path:**
```
pm_create_story(
  title="[SMOKE] Cross-reference smoke-test in cleanup skill",
  epic_id=<epic_id>,
  write_files=["skills/smoke-test/SKILL.md", "skills/cleanup/SKILL.md"],
  agent="architect",
  tasks=[
    "Add a note in skills/cleanup/SKILL.md referencing the smoke-test teardown pattern",
    "Add a corresponding back-reference in skills/smoke-test/SKILL.md"
  ]
)
```

Record all returned story IDs.

---

## Step 3: Run Gemini planning

Load `ToolSearch: select:mcp__gemini__pm_plan_stories`.

Call `pm_plan_stories(epic_id=<epic_id>, project_root="~/.claude")`.

This mirrors what `/ship` Step 1 does via the planner agent. Wait for it to complete.

---

## Step 4: Launch plan-writer agents

Replicate the `/ship` Step 3b plan-writer agent pattern exactly.

### Step 4a: Prepare plan-writer launches

1. Read `refs/orch-critique-checklist.md` — keep its full content for the agent prompts.
2. For each story, call `pm_get_story(story_id)` — read the detail file for tasks and write_files.
3. Glob `plans/*.md` once to get existing names. For each story, generate a unique plan file name with a `smoke-` prefix: `plans/smoke-alpha.md`, `plans/smoke-beta.md`, `plans/smoke-gamma.md` (or similar — avoid collisions with existing files).

### Step 4b: Launch plan-writer agents

Launch one `general-purpose` background agent per story with `run_in_background: true`. Use this prompt template for each:

```
You are writing a plan file for story <story_id>: "<title>"

Agent: <agent>
Tasks: <task list from pm_get_story>
Write files: <write_files list>
Read files: <read_files list>
Output file: plans/<smoke-name>.md

## Critique Checklist
<full checklist content from refs/orch-critique-checklist.md>

## Instructions

1. Read the story's write_files to understand what exists today.
2. Read files referenced by tasks but not in write_files — these become read-only context.
3. Apply the critique checklist against the Gemini-planned tasks:
   - If SIGNIFICANT issues found (missing files, scope creep, convention violations):
     Return: "NEED_DECISION: <issue>\nOption A: <fix>\nOption B: <fix>"
   - If MINOR gaps (edge cases, existing utilities): incorporate silently.
4. Write the plan file to plans/<smoke-name>.md with this structure:

   # <story title>

   Story: <story_id>
   Agent: <agent>

   ## Context

   <Brief description of what this story accomplishes>

   ## What changes

   | File | Change |
   |---|---|
   | <write_file> | <description from tasks> |

   ## Read-only context

   These files inform the implementation but should not be modified:
   - `path/to/file` — why it's relevant

   ## Tasks

   1. <task 1>
   2. <task 2>

   ## Acceptance criteria

   These define correctness independently of the implementation. Tests should verify these:
   - <observable behavior 1>
   - <observable behavior 2>

   ## Verification

   - <how to verify the changes work>

5. Return: "DONE: plans/<smoke-name>.md"
```

### Step 4c: Collect results

Wait for all background agents to complete. For each result:

- `DONE: plans/<name>.md` — Load `ToolSearch: select:mcp__gemini__pm_update_story`, then call `pm_update_story(story_id=<id>, plan_file="plans/<name>.md")`.
- `NEED_DECISION: <issue>` — Log as a warning (do not block the smoke test for this). Note: "Plan-writer raised a decision — this is expected behavior for the pipeline but unexpected for a smoke test with trivial tasks."
- `BLOCKED: <reason>` — Log as a failure for this story.

---

## Step 5: Validate results

Run all checks independently. Collect pass/fail for each. Do NOT stop on failure — run every check regardless.

Initialize a results tracker:
```
checks = {
  "plan_files_exist": { passed: 0, total: 0, details: [] },
  "required_sections": { passed: 0, total: 0, details: [] },
  "db_plan_file_set": { passed: 0, total: 0, details: [] },
  "story_states": { states: [] },
  "no_duplicate_tasks": { passed: 0, total: 0, details: [] },
  "plan_file_nontrivial": { passed: 0, total: 0, details: [] }
}
```

### 5a. Plan files exist

For each story, read the plan file at its expected path. If the file exists and is readable, PASS. If not, FAIL with the missing path.

### 5b. Required sections

Each plan file must contain all of these headings:
- `## What changes` (or `## Context`)
- `## Tasks`
- `## Acceptance criteria`

Read each plan file and search for these headings. A plan file passes if all three are present.

### 5c. DB state — plan_file set

Load `ToolSearch: select:mcp__gemini__pm_get_story`.

For each story, call `pm_get_story(story_id)` and read the detail file. Verify `plan_file` is non-null and matches the expected `plans/smoke-*.md` path.

### 5d. DB state — story state

For each story (from the same `pm_get_story` calls in 5c), record the current state. This is informational — note the actual state but do not mark it as a hard failure.

### 5e. No duplicate tasks

From each story's detail file, extract all task titles. Confirm no title appears more than once within a single story.

### 5f. Plan file content is non-trivial

Each plan file should be >100 bytes. Read each file and check its size. Catches empty or stub files.

---

## Step 6: Teardown

Clean up all smoke-test artifacts. This step runs unconditionally — even if validation checks failed.

1. Delete generated plan files:
   ```bash
   rm plans/smoke-*.md 2>/dev/null || true
   ```

2. Load `ToolSearch: select:mcp__gemini__pm_update_story,mcp__gemini__pm_update_epic`.

3. For each story:
   ```
   pm_update_story(story_id, state="done", force=True)
   ```

4. Close the epic:
   ```
   pm_update_epic(epic_id, state="done")
   ```

Do NOT attempt to delete the epic from the DB (no such API). Closing the epic + marking stories done is sufficient.

---

## Step 7: Report

Print a summary table with individual check results:

```
Smoke test: ship pipeline

Check                    Result
---------------------------------------
Plan files exist         PASS/FAIL (N/M)
Required sections        PASS/FAIL (details per file)
DB plan_file set         PASS/FAIL (N/M)
Story states             INFO: [list of states]
No duplicate tasks       PASS/FAIL (N/M)
Plan file non-trivial    PASS/FAIL (N/M)

Teardown: complete

Result: PASS / FAIL (N of M checks passed)
```

Count a check as PASS only if all sub-items within it passed. The overall result is PASS only if all non-INFO checks passed.
