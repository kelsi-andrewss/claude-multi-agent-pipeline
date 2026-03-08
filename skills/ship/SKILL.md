---
name: ship
description: "One-shot pipeline: idea to running coders in a single command. Creates epic, stories, tasks, plan files, and launches execution. Use when the user says \"/ship <title> <features>\", \"/ship path/to/prd.md\", \"/ship plans/existing-plan.md\", or \"/ship epic-NNN\"."
args:
  - name: args
    type: string
    description: "Title + feature list, PRD file path, plan file path, or epic ID."
---

# Ship Skill Invoked

User has requested: `/ship {{args}}`

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to determine the mode:

**Flags:**
- If `--quick` appears anywhere in args, set `skip_validate = true` and `skip_verify = true`. Strip from args. Skips plan validation (analyze/argue), integrated review, and integration verify. Per-story testing always runs (it's a run-stories concern, not a ship concern).
- If `--argue` appears anywhere in args, set `use_argue = true`. Strip from args. Uses adversarial debate instead of single-pass review for plan validation.

1. **Resume mode**: first token matches `epic-\d+` → set `epic_id` to that token.
2. **File mode**: a token ends with `.md` and the file exists → read it:
   - If file contains `## What changes` → **Execute mode** (existing plan file).
   - Otherwise → **PRD mode** (requirements doc). Read file contents, then check for a `## Summary` section:
     - If `## Summary` exists → **presearch briefing**. Extract `## Summary` content as `context` (not the full file). Extract numbered items from `## Features` > `### MVP` as `items`. Store the briefing path as `briefing_path` for use in Step 3. Read and store the full file contents as `briefing_contents` for use in Steps 2c and 2d.
     - If `## Summary` absent → existing behavior (full file as `context`).
3. **Inline mode**: everything else. Extract:
   - Quoted string or text before numbered items → `title`
   - `by YYYY-MM-DD` → `target_date`
   - Remaining numbered or comma-separated items → `items` list

   **Sufficiency check (inline mode only):** After parsing, check for actionable signals:
   - Specific technologies/frameworks mentioned? (e.g., "Stripe", "React", "Firebase")
   - Existing file paths referenced?
   - Numbered feature items (≥2)?
   - If ANY of these signals are present → pass through silently.
   - If NONE are present (pure prose, no structure), warn:
     ```
     This looks like a high-level idea. /presearch produces better results by
     researching APIs and constraints first. Continue anyway? (y/presearch)
     ```
   - User says "y" or similar → continue. User says "presearch" → invoke `/presearch` with the same args. This is a warning, not a gate.

4. **No args**: Ask the user: "Describe what to build (features or file path):" and stop.

---

## Step 1: Dispatch to planner or execute mode

### Execute mode (existing plan file)

If **Execute mode** was detected in Step 0:

1. Read the plan file and parse:
   - **Title**: first `# ` heading
   - **Agent**: value from `Agent:` line (if present)
   - **Write targets**: file paths from the first column of the `## What changes` table (skip header row and `|---|` separator)

2. Load `ToolSearch: select:mcp__gemini__pm_create_story,mcp__gemini__pm_update_story,mcp__gemini__pm_create_epic`

3. **Route by scope:**

   **Quick-fix path (≤2 write targets):**
   - No epic — omit `epic_id` (story lands in `epic-backlog`)
   - Agent: parsed `Agent:` line, or `quick-fixer`
   - Auto-set `skip_validate = true` and `skip_verify = true` (same effect as `--quick`)
   - `pm_create_story(title=<title>, agent=<agent>, write_files=<write targets>)`
   - `pm_update_story(story_id=<new id>, plan_file="<plan file path>")`
   - Go to Step 4

   **Full path (>2 write targets):**
   - `pm_create_epic(title=<title>)` → use returned `epic_id`
   - Agent: parsed `Agent:` line, or `architect`
   - Respect user-provided `--quick`/`--argue` flags (don't auto-set)
   - `pm_create_story(title=<title>, epic_id=<epic_id>, agent=<agent>, write_files=<write targets>)`
   - `pm_update_story(story_id=<new id>, plan_file="<plan file path>")`
   - Go to Step 4

### All other modes — delegate to planner agent

Launch the **planner** agent (foreground) with the parsed inputs:

```
Agent(subagent_type="planner", prompt="""
MODE: ship
TITLE: <title>
ITEMS: <items list>
FLAGS: <--quick and/or --argue if set>
CONTEXT: <briefing_contents if presearch mode, otherwise omit>
""")
```

For **Resume mode**, include `EPIC_ID: epic-NNN` instead of TITLE/ITEMS.

Wait for the planner to return.

**On PLANNER_RESULT**: Extract `epic_id`, `dev_branch`, story list (IDs, titles, agents, detail_file paths). Proceed to Step 3.

**On PLANNER_ERROR**: Surface the error to the user with full details (step, tool, error message, partial results). Do NOT fall back to direct MCP calls — the failure causes (MCP down, Gemini garbage, agent context limit) would also fail in the main session. Let the user decide: retry, adjust input, or abort.

---

## Step 3: Write plan files (background agents)

Plan files are written by parallel background agents to preserve main-session context.

### Step 3a: Prepare plan-writer launches

1. Read `refs/orch-critique-checklist.md` once (keep its content for the agent prompts).
2. For each story, call `pm_get_story(story_id=<id>)` — read the detail file for tasks and write_files.
3. Glob `plans/*.md` once to get existing names. For each story, generate a unique plan file name: `plans/<random-adjective-noun>.md`.

### Step 3b: Launch plan-writer agents

Launch one `general-purpose` background agent per story with `run_in_background: true`. Use this prompt template for each:

```
You are writing a plan file for story <story_id>: "<title>"

Agent: <agent>
Tasks: <task list from pm_get_story>
Write files: <write_files list>
Read files: <read_files list>
Output file: plans/<name>.md

## Critique Checklist
<full checklist content from refs/orch-critique-checklist.md>

## Instructions

1. Read the story's write_files to understand what exists today.
2. Read files referenced by tasks but not in write_files — these become read-only context.
3. Apply the critique checklist against the Gemini-planned tasks:
   - If SIGNIFICANT issues found (missing files, scope creep, convention violations):
     Return: "NEED_DECISION: <issue>\nOption A: <fix>\nOption B: <fix>"
   - If MINOR gaps (edge cases, existing utilities): incorporate silently.
4. Write the plan file to plans/<name>.md with this structure:

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

5. If briefing_path was provided, include it in read-only context and reference
   specific sections in task descriptions.
   Format: (see briefing ## <Section> > <Subsection> for <what>)
6. Return: "DONE: plans/<name>.md"
```

If `briefing_path` was set in Step 0, append to each agent's prompt:
```
Briefing path: <briefing_path>
Include this file in read-only context. Reference specific briefing sections in
task descriptions for any task involving APIs, data models, patterns, or gotchas.
```

### Step 3c: Collect results

Wait for all background agents to complete. For each result:

- `DONE: plans/<name>.md` — Load `ToolSearch: select:mcp__gemini__pm_update_story`, then call `pm_update_story(story_id=<id>, plan_file="plans/<name>.md")`.
- `NEED_DECISION: <issue>` — Surface to user, get answer, resume agent.
- `BLOCKED: <reason>` — Report to user, skip story.

Proceed to Step 3d after all agents complete.

---

## Step 3d: Critique loop

**Skip when:** `skip_validate = true` (--quick flag).

After all plan files are written and stored in the DB, run the critique loop on each:

1. For each plan file from Step 3c, invoke the critique logic (Step 3–4 from `/critique` SKILL.md):
   - Self-critique: 2 passes max, 5 core questions, NMIP gating per question.
   - Gemini escalation: use `mcp__gemini__pm_critique` (story IDs are available) instead of `mcp__gemini__analyze`.
   - Fix improvements inline in the plan files.
2. After all plan files are critiqued, note findings for the Step 5a report:
   - Which plans were improved and what changed.
   - Any remaining concerns Gemini raised that weren't resolved.
   - Past blind spots checked (from OpenMemory).
3. Store learnings per `/critique` Step 5 (tool-learning tag, blind spots if Gemini caught NMIP'd items).

Do NOT append `## Self-critique` sections to plan files — coders don't need critique metadata. Findings go in the Step 5a report only.

---

## Step 3e: Environment preflight

**Purpose**: Identify external service dependencies before coders launch. Missing env vars waste entire coder runs.

**Skip when**: Execute mode (existing plan file — user manages their own env).

**NEVER read `.env` files.** This step works with service *names* from plan text — never secret values.

1. Scan all plan files from Step 3. In `## What changes` and `## Tasks` sections, look for indicators of external dependencies:
   - Auth providers (Firebase Auth, Supabase, Auth0, Clerk, OAuth)
   - Databases (Postgres, MySQL, MongoDB, Redis, Firestore)
   - Payment (Stripe, PayPal, Square)
   - Email/SMS (SendGrid, Twilio, Resend, Postmark)
   - Cloud SDKs (AWS, GCP, Azure)
   - Explicit env var references (process.env, os.environ, dotenv)

2. If nothing detected → skip silently, proceed to Step 4.

3. If dependencies detected → present a checklist of env var **names** (never values) and **wait for user confirmation**:
   ```
   Environment preflight — external services detected in plan files:

   [ ] STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY — Stripe payments (story-NNN)
   [ ] DATABASE_URL — PostgreSQL (story-NNN, story-MMM)
   [ ] FIREBASE_API_KEY — Firebase Auth (Bootstrap)

   Confirm these are set in your .env (and anywhere else needed), or say "skip".
   ```

4. For new projects: ensure the Bootstrap plan includes:
   - `.env.example` with placeholder var names (no real values)
   - `.env` and `.env.local` in `.gitignore`

---

## Step 4: Execute

Collect all story IDs (space-separated) and invoke:

```
Skill: run-stories, args: "<story-id-1> <story-id-2> ..."
```

---

## Step 5a: Report execution status

After `/run-stories` completes, print a summary:
```
Shipped: <epic title> (<epic_id>)
  story-NNN: <title> — <agent> — plan: plans/<name>.md — <DONE|BLOCKED>
  ...
```

If any stories are BLOCKED, list their reasons. Continue to Step 5b only if at least one story merged successfully.

---

## Step 5b: Integrated review

**Skip when:** `skip_verify = true` (--quick flag) or zero stories merged.

After all stories merge into the dev branch, review the combined output:

1. Determine `<dev-branch>` from the epic mapping and `<base>` (the commit the dev branch was created from, or `main`).
2. Generate the full diff: `git diff <base>...<dev-branch>`
3. Launch reviewer agent (background, **Sonnet**) on the full diff. The reviewer sees the combined output of all stories and checks for:
   - Cross-story naming inconsistencies
   - Duplicate code across stories
   - Conflicting patterns or import inconsistencies
   - Any BLOCKING issues
4. Results:
   - BLOCKING findings → report which story likely caused each issue. Attempt fix via coder resume or manual fix on dev branch.
   - Warnings → log to `<project>/.claude/review-findings.md`.
   - Max 1 review round.

---

## Step 5c: Integration verify

**Skip when:** `skip_verify = true` (--quick flag) or no build system detected.

After integrated review passes (or was skipped), verify the combined result:

1. Checkout dev branch: `git checkout <dev-branch>`
2. Detect project type and run build:
   - `package.json` → `npm install && npm run build`
   - `pubspec.yaml` → `flutter pub get && flutter build`
   - `Cargo.toml` → `cargo build`
   - `go.mod` → `go build ./...`
   - `pyproject.toml`/`setup.py` → `pip install -e .`
   - None detected → skip, warn "No build system detected."
3. Build failure → report error + identify likely story cause from the diff.
4. Run tests if infrastructure exists. Failure → report failing tests.
5. Behavioral checks: walk acceptance criteria from all plan files. For each criterion that can be checked programmatically:
   - API endpoints → curl/fetch and verify response shape + status
   - CLI commands → run and verify output
   - File output → check file exists and contents match expectations
   - UI/visual criteria → skip, report as "manual verification needed: `<criterion>`"
6. Report:
   ```
   Integration verified: build passes, N/M tests pass, K/L acceptance criteria verified, J criteria require manual check.
   ```
7. Return to original branch.

---

## Step 6: Final report

Print final summary:
```
Ship complete: <epic title> (<epic_id>)
  Stories: N merged, M blocked
  Review: <pass|warnings|blocking issues found>
  Integration: <build passes, tests pass|build failed|skipped>
  Acceptance: K/L verified, J manual

Use /roadmap to check status.
```
