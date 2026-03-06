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
   - If path starts with `plans/` and file contains `## What changes` → **Execute mode** (existing plan file).
   - Otherwise → **PRD mode** (requirements doc). Read file contents as `context`.
3. **Inline mode**: everything else. Extract:
   - Quoted string or text before numbered items → `title`
   - `by YYYY-MM-DD` → `target_date`
   - Remaining numbered or comma-separated items → `items` list
4. **No args**: Ask the user: "Describe what to build (features or file path):" and stop.

---

## Step 1: Load tool

```
ToolSearch: select:mcp__gemini__pm_ship
```

---

## Step 2: Call pm_ship (one tool call)

Based on mode:

- **Inline mode**: `pm_ship(items=[...], title="...", target_date=<or null>)`
- **PRD mode**: `pm_ship(items=[...extracted feature lines...], title="...", context=<file contents>)`
- **Resume mode**: `pm_ship(items=[], epic_id="epic-NNN")`
- **Execute mode**: Skip pm_ship entirely. Go to Step 2b.

### Step 2b: Execute mode (existing plan file)

For an existing plan file:
1. Read the plan file.
2. Extract the title from the first `# ` heading.
3. Load `ToolSearch: select:mcp__gemini__pm_create_story`
4. Call `pm_create_story(title=<extracted title>, agent="architect")`.
5. Load `ToolSearch: select:mcp__gemini__pm_update_story`
6. Call `pm_update_story(story_id=<new story id>, plan_file="<plan file path>")`.
7. Go to Step 4 with that single story ID.

---

## Step 2c: Run Gemini planning

`pm_ship` only creates the epic and stories in the DB — it does NOT run Gemini planning.

After Step 2 (or Step 2b), run Gemini planning as a separate step:

1. Note `epic_id` from the `pm_ship` response (read the detail file at the path in the response if needed).
2. Call `pm_plan_stories(epic_id=<epic_id>)` to generate tasks, write_files, agent assignments, and parallel groups for all draft stories.
3. Read the detail file for planned stories with tasks and execution order.

**Skip this step in Execute mode** (Step 2b), since that path uses a pre-written plan file.

---

## Step 2d: Plan validation

**Skip when:** `skip_validate = true` (--quick flag) or Execute mode.

Validate the plan and produce acceptance criteria before writing plan files:

1. Fetch all stories: `pm_list_stories(epic_id=<epic_id>)`.
2. Assemble a plan summary: for each story, list title, agent, write_files, tasks.

**Default path** (no `--argue` flag):

3. Load analyze: `ToolSearch: select:mcp__gemini__analyze`
4. Call `analyze(input="Review this implementation plan for <epic title>. For each story: 1) Check decomposition, file targets, and missing dependencies. 2) Define concrete acceptance criteria — observable behaviors proving correctness (e.g., 'GET /users returns 200 with user list', 'clicking Submit shows confirmation modal'). Format acceptance criteria under per-story headings.\n\n<plan summary>")`.
5. Parse response:
   - Plan issues → adjust in Step 3 plan files or call `pm_update_story`.
   - Acceptance criteria → extract per-story criteria and include in plan files (Step 3).

**`--argue` path** (`use_argue = true`):

3. Write plan summary to `/tmp/ship-plan-<epic-id>.md`.
4. Load argue: `ToolSearch: select:mcp__gemini__argue`
5. Call `argue(topic="Implementation plan for <epic title>: 1) Verify decomposition, file targets, approach, and missing dependencies. 2) For each story, define concrete acceptance criteria — observable behaviors that prove the story works correctly. Output these under a per-story ACCEPTANCE CRITERIA heading.", topic_type="plan", context_docs=["/tmp/ship-plan-<epic-id>.md"], max_rounds=3)`.
6. Parse synthesis:
   - Plan issues → adjust in Step 3 plan files or call `pm_update_story`.
   - Acceptance criteria → extract per-story criteria and include in plan files (Step 3).
7. Delete temp file: `rm /tmp/ship-plan-<epic-id>.md`

---

## Step 3: Write plan files (Claude's job)

For each story, call `pm_get_story(story_id=<id>)` — read the detail file for tasks and write_files. Then for each story:

1. Generate a plan file name: `plans/<random-adjective-noun>.md`
2. Write the plan file with this structure:
   ```
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
   ...

   ## Acceptance criteria

   These define correctness independently of the implementation. Tests should verify these:
   - <observable behavior 1>
   - <observable behavior 2>

   ## Verification

   - <how to verify the changes work>
   ```

   **Read-only context:** Determine from files referenced by tasks but not in the story's write_files scope. These give coders the interface contracts and utilities they need without modifying them.

   **Acceptance criteria:** If plan validation ran (Step 2d), extract per-story criteria from the analyze/argue response. If validation was skipped (`--quick`), write basic criteria derived from the story's task descriptions — focus on observable behaviors, not implementation details.

3. Load `ToolSearch: select:mcp__gemini__pm_update_story`
4. Call `pm_update_story(story_id=<id>, plan_file="plans/<name>.md")` for each story.

---

## Step 3b: Environment preflight

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

1. Determine `<dev-branch>` from the epic mapping and `<base>` (the commit the dev branch was created from, i.e. where it diverged from `dev`).
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
