---
name: smoke-test
description: >
  Pipeline output quality validation. Generates a real app via /ship, builds it,
  and grades wiring quality with deterministic checks. Default mode ("quality")
  generates a recipe app and validates build + wiring. "ship" mode runs the
  legacy structural pipeline validation.
args:
  - name: args
    type: string
    description: >
      Test mode to run. "quality" (default) generates and validates a real app.
      "ship" runs legacy structural pipeline validation.
---

# Smoke Test Skill Invoked

User has requested: `/smoke-test {{args}}`

---

## Step 0: Parse args and select mode

Inspect `{{args}}` (trim whitespace):

- **Empty or "quality"** — Proceed to **Quality mode** (Step 1).
- **"ship"** — Jump to **Ship mode** section below.
- **Anything else** — Print usage and stop:
  ```
  Usage: /smoke-test [mode]

  Available modes:
    quality — (default) Generate a recipe app, build it, grade wiring quality
    ship    — Legacy structural pipeline validation (DB state, plan files)
  ```

---

# Quality Mode

## Step 1: Create isolated test repo

Create a temp directory and initialize it as a standalone git repo with a minimal Node/TS scaffold:

```bash
SMOKE_DIR=$(mktemp -d /tmp/smoke-test-XXXXXX)
cd "$SMOKE_DIR"
git init
git checkout -b main
echo '{"name":"smoke-test-recipe-app","private":true,"scripts":{"dev":"next dev","build":"next build"}}' > package.json
echo '{"compilerOptions":{"target":"es5","lib":["dom","dom.iterable","esnext"],"allowJs":true,"skipLibCheck":true,"strict":true,"noEmit":true,"esModuleInterop":true,"module":"esnext","moduleResolution":"bundler","resolveJsonModule":true,"isolatedModules":true,"jsx":"preserve","incremental":true,"plugins":[{"name":"next"}],"paths":{"@/*":["./src/*"]}},"include":["next-env.d.ts","**/*.ts","**/*.tsx"],"exclude":["node_modules"]}' > tsconfig.json
mkdir -p src/app
echo 'export default function RootLayout({ children }: { children: React.ReactNode }) { return (<html><body>{children}</body></html>) }' > src/app/layout.tsx
echo 'export default function Home() { return <main>Hello</main> }' > src/app/page.tsx
git add -A && git commit -m "init: Next.js scaffold"
git checkout -b dev
```

Record `SMOKE_DIR` for use in subsequent steps. The main session MUST `cd` to `SMOKE_DIR` before invoking /ship in Step 2.

---

## Step 2: Generate app via /ship

**IMPORTANT: Change working directory to `$SMOKE_DIR` before running /ship.** All /ship operations (story creation, worktrees, merges) will target the temp repo, not ~/.claude.

```bash
cd "$SMOKE_DIR"
```

Use this hardcoded test fixture prompt:

```
Build a recipe search app. Next.js App Router, single page. Search bar at top that queries TheMealDB free API. Results show as cards with thumbnail, name, and category. Clicking a card opens a detail modal with full ingredients list and instructions. Users can bookmark recipes and see their bookmarks in a sidebar toggle.
```

Run:
```
/ship --quick "<the prompt above>"
```

The `--quick` flag skips critique/verify since the smoke test has its own validation.

Wait for `/ship` to complete before proceeding. Then `cd` back to the orchestration project root:

```bash
cd ~/.claude
```

---

## Step 3: Set app directory

After /ship completes, the generated code is on the dev branch of the temp repo. No cloning needed.

```bash
# Checkout dev branch which has the merged code
git -C "$SMOKE_DIR" checkout dev
APP_DIR="$SMOKE_DIR"
```

Verify the app has source files:
```bash
ls "$APP_DIR/src/" 2>/dev/null
```

If no source files exist, report FAIL and skip to Step 7 (teardown).

---

## Step 4: Run project-validator.sh

```bash
VALIDATOR_JSON=$(bash ~/.claude/scripts/project-validator.sh --project-root "$APP_DIR")
```

Parse the JSON result. Record:
- `validator_status`: the top-level `status` field
- `framework`: the detected framework
- Per-layer results (install, build, typecheck)

---

## Step 5: Run wiring-checklist.sh

```bash
WIRING_JSON=$(bash ~/.claude/scripts/wiring-checklist.sh --project-root "$APP_DIR")
```

Parse the JSON result. Record:
- `wiring_status`: the top-level `status` field
- `wiring_score`: the `score` field (e.g. "7/8")
- Per-check results

---

## Step 6: Grade

**PASS** if both conditions are met:
1. `validator_status` is `"pass"` (install + build + typecheck all succeed)
2. Wiring score is >= 6/8

**FAIL** otherwise.

---

## Step 7: Teardown

Runs unconditionally, even if earlier steps failed.

1. Remove temp directory:
   ```bash
   rm -rf "$SMOKE_DIR"
   ```

2. Archive the smoke-test epic (if one was created by /ship):
   ```
   /cleanup epic-<id>
   ```

---

## Step 8: Report

Print a summary table:

```
Smoke test: quality validation

Layer              Status    Output (last line)
--------------------------------------------------
install            PASS/FAIL <last line of output>
build              PASS/FAIL <last line of output>
typecheck          PASS/FAIL <last line of output>

Wiring Check       Status    Matches
--------------------------------------------------
event_binding      PASS/FAIL N
fetch_to_state     PASS/FAIL N
click_to_state     PASS/FAIL N
conditional_render PASS/FAIL N
shared_state       PASS/FAIL N
toggle_pattern     PASS/FAIL N
modal_close        PASS/FAIL N
key_handler        PASS/FAIL N

Wiring score: N/8
Build status: PASS/FAIL

Overall: PASS / FAIL
```

---

# Ship Mode

Legacy structural pipeline validation. Creates throwaway stories, runs planning agents, validates DB state and plan file structure, then tears down.

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
