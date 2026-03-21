---
name: merge-worktree
description: >
  Merge a story worktree branch into its dev branch, push, clean up the worktree and branches,
  and mark the story done. Use when the user says "/merge-worktree", "/merge-worktree story-NNN",
  or "merge worktree".
args:
  - name: args
    type: string
    description: >
      Optional. A single story ID (story-NNN) to merge, or empty to auto-detect the most
      recently modified story worktree under .claude/worktrees/story/.
      Or "--queue" to auto-merge all done stories with active worktrees in dependency order.
      Or "--queue --dry-run" to preview what would be merged without executing.
---

# Merge Worktree Skill Invoked

User has requested: `/merge-worktree {{args}}`

## Decision rules (from ORCHESTRATION §8)

**NEED_DECISION handling**: If a coder returned NEED_DECISION, the main session picks an option and resumes the coder before merging. Story stays `in-progress`, worktree preserved.

**Escalation**: 2 BLOCKING round-trips → escalate coder to Opus (architect stories only). Log friction: category `escalation`. Opus still BLOCKING → story `blocked`, report to user. Log friction: category `blocked`.

**Restart (plan-level failure)**: If coder failed because the plan was wrong (wrong files, missing utility, wrong scope) — not because the coder was incapable:
1. Log friction: category `restart`.
2. Reset worktree: `git -C <worktree> reset --hard HEAD && git -C <worktree> clean -fd`
3. Write new plan file referencing what failed: "Previous plan assumed X, but Y is actually the case."
4. Relaunch at same model level (pivot, not escalation).
5. Max 1 restart per story. Second failure → `blocked`, report.

**Restart vs. escalation**: If coder did exactly what the plan said and it didn't work → restart. If coder couldn't execute a sound plan → escalation.

---

## Batch Mode (Subagent Delegation)

When the caller has **2+ stories** to merge (e.g., run-stories Step 5c with multiple validated stories), launch ONE foreground `general-purpose` subagent instead of executing merge-worktree inline for each story.

### When to use batch mode

- **Use**: run-stories Step 5c with 2+ validated stories, /ship with multiple stories completing simultaneously
- **Do NOT use**: single `/merge-worktree story-NNN` invocation, `/quickfix` merge step (always single-story)

### Subagent prompt construction

Build a prompt containing:

1. The full text of Steps 1 through 5.6 below (the single-story merge procedure). The Step 4 cleanup uses `worktree-cleanup.sh` — include the script invocation syntax in the prompt.
2. The batch story list with pre-resolved data for each story:
   - `story_id`, `title`, `epic_id`
   - `story-branch` (already computed by run-stories)
   - `worktree-path` (already known from coder agent)
   - `dev-branch`: `dev`
   - `test_result` from run-stories Step 5b (pass, skip, or pass (spec tests))
   - `write_files` (JSON array of file paths from the story's write_files field)
   - `plan_file` (path to the story's plan file)
   - `acceptance_criteria` (text of the ## Acceptance criteria section from the plan file, or empty string if none)
3. ToolSearch instructions: `select:mcp__gemini__pm_update_story,mcp__gemini__pm_update_epic,mcp__gemini__pm_get_story`
4. The queue-based merge coordination instructions (Phase 0 through Phase 3 below).
5. The return format (see below)

### Diff gate (per story, inside subagent)

Before merging each story, the subagent runs the diff gate:

```bash
DIFF_RESULT=$(bash ~/.claude/scripts/diff-gate.sh --worktree-path <worktree-path> --dev-branch <dev-branch> --write-files "<comma-separated write_files>")
```

Parse the JSON result. If `unexpected_files` is non-empty:
- Log the discrepancy in the return summary
- Continue with the merge (non-blocking, same as current behavior)

### Subagent execution loop (queue-based)

Merges are coordinated through `merge-queue.py`. Non-conflicting stories (no write-target overlap with anything actively merging) proceed immediately; conflicting stories wait until the conflicting predecessor finishes.

**Phase 0 — Stale cleanup** (before enqueuing):

```bash
STALE=$(python3 ~/.claude/scripts/merge-queue.py status)
```

Parse the JSON result. For any row with status `merging` or `queued`, cancel it:
```bash
python3 ~/.claude/scripts/merge-queue.py cancel --story-id <story_id>
```
This prevents stale rows from previous sessions from blocking the current batch.

**Phase 1 — Enqueue all stories:**

For each validated story:

1. **Diff gate** — as above
2. **Enqueue**:
   ```bash
   ENQUEUE_RESULT=$(python3 ~/.claude/scripts/merge-queue.py enqueue \
     --story-id <story_id> \
     --write-targets '<write_files_json>' \
     --priority <priority>)
   ```
   Priority assignment:
   - quickfix stories: 2
   - architect stories: 1
   - all others: 0

**Phase 2 — Drain the queue:**

Initialize `stall_counter = 0`. Loop until queue is empty or stalled:

1. ```bash
   NEXT_RESULT=$(python3 ~/.claude/scripts/merge-queue.py next)
   ```
2. Parse the `action` field:
   - `"next"`: safe story found. Execute merge (Step 3 logic) for that story.
     On merge success:
       ```bash
       python3 ~/.claude/scripts/merge-queue.py dequeue --story-id <story_id>
       ```
       Continue with Steps 4, 5, 5.5 for that story. Increment `merged_via_skip` counter.
       Reset `stall_counter = 0`.
     On merge conflict:
       ```bash
       python3 ~/.claude/scripts/merge-queue.py cancel --story-id <story_id>
       ```
       Record as blocked. Continue draining.
   - `"none"` with reason `"queue_empty"`: all done. Exit loop.
   - `"none"` with reason `"all_blocked"`:
       Increment `stall_counter`.
       If `stall_counter >= 3`: fall back to sequential — cancel all queued stories,
       re-enqueue one at a time, merge each before enqueuing next.
       Increment `stall_fallbacks` counter.
       Else: continue loop (the next iteration re-checks after the current merge completes).

**Phase 3 — Report** (unchanged Step 6)

### Required return format

```
MERGE_SUMMARY:
  merged: [story-NNN, story-MMM, ...]
  blocked: [story-PPP (conflict: file.ts)] | none
  commit_hashes: {story-NNN: abc1234, story-MMM: def5678}
  epic_closures: [epic-NNN] | none
  warnings: ["story-NNN: unexpected files changed: foo.ts"] | none
  test_results: {story-NNN: "pass", story-MMM: "skip"}
  outcomes_logged: [story-NNN, story-MMM]
  queue_stats: {enqueued: 5, merged_via_skip: 3, waited: 2, stall_fallbacks: 0}
  regressions: {story-NNN: {checked: 3, failed: 0}, story-MMM: {checked: 5, failed: 1, details: ["story-AAA criterion X failed: error"]}} | none
```

`merged_via_skip`: stories that merged immediately because they had no write-target overlap with anything in the queue at the time. This is the throughput metric -- higher means the queue is doing its job.

### What the main session does after

1. Parse the `MERGE_SUMMARY` structured response
2. Use `merged`, `blocked`, `commit_hashes` to populate the Step 6 report
3. No further MCP calls needed — the subagent already updated DB state and logged outcomes
4. If any stories are `blocked`, include them in the run-stories blocked section

### Context savings

A 5-story batch that previously produced ~30 tool call responses in main context now produces 1 structured summary (~15 lines). The subagent's internal git output, MCP responses, and outcome logging are invisible to the main session.

---

## Queue Mode (Auto-merge)

Invoked as `/merge-worktree --queue`. Discovers and merges all eligible stories automatically.

### When to use

- run-stories Step 5c: after a batch of stories pass validation, call `/merge-worktree --queue` instead of enumerating IDs
- Main session cleanup: merge all completed work in one command
- Automated pipelines: no human-in-the-loop required

### Step Q1: Discover eligible stories

1. Call `pm_list_stories()` across all active epics.
2. Filter to stories where `state = "done"` AND `worktree_active = true`.
3. If no stories match, report: "No stories eligible for auto-merge." and stop.

### Step Q2: Check hold list

Read `.claude/merge-holds.json` from the project root:

```bash
HOLDS=$(cat .claude/merge-holds.json 2>/dev/null || echo '[]')
```

Parse as a JSON array of story IDs. If parsing fails, treat as empty (no holds).

For each eligible story, check if its ID is in the hold list. If so, mark it `ON HOLD` and exclude from merge processing.

### Step Q3: Dependency ordering

Order remaining stories by dependency (topological sort):

1. For each story, read `depends_on` from the story data.
2. Build a dependency graph across all eligible stories.
3. Sort topologically:
   - Group 0: no unmerged dependencies
   - Group 1: all dependencies in Group 0
   - Group N: all dependencies in earlier groups
4. If a story depends on something not in the eligible set and not already `done`/`shipped`, defer it:
   > "story-NNN: DEFERRED — depends on story-MMM (not done)"

### Step Q4: Execute merges

Process stories in dependency order. For each story, execute the standard merge procedure (Steps 1 through 5.5) with these modifications:

- **No approval gate**: merges proceed automatically.
- **Conflict handling**: if a merge conflicts, skip the story (do not abort the queue). Record it as `CONFLICT` in the summary.
- **Hold check**: already filtered in Step Q2, but double-check before each merge in case the file was updated mid-run.

Use batch mode (subagent delegation) when 2+ stories are eligible after filtering. Use single-story inline execution when only 1 story remains.

### Step Q5: Report

Print the auto-merge summary:

```
Auto-merge complete:
  story-NNN: merged (abc1234)
  story-MMM: merged (def5678)
  story-PPP: ON HOLD — skipped
  story-QQQ: CONFLICT — <conflict description>
  story-RRR: DEFERRED — depends on story-SSS
```

This is the only output. The main session parses it the same way it parses the batch mode `MERGE_SUMMARY`.

---

## Hold Flag

Stories can be excluded from auto-merge (queue mode) by adding their ID to `.claude/merge-holds.json`.

### File format

```json
["story-123", "story-456"]
```

An array of story ID strings. The file lives at `<project-root>/.claude/merge-holds.json`.

### Behavior

- **Queue mode**: checks the hold list before each merge. Held stories are skipped with `ON HOLD` status.
- **Single-story mode**: ignores the hold list. Explicit `/merge-worktree story-NNN` always merges.
- **Batch mode**: ignores the hold list. Explicit story ID lists always merge.
- **Missing/malformed file**: treated as empty — no stories held.

### Managing holds

Add a hold:
```bash
python3 -c "
import json, os
f = '.claude/merge-holds.json'
holds = json.load(open(f)) if os.path.exists(f) else []
holds.append('story-NNN')
json.dump(sorted(set(holds)), open(f, 'w'))
"
```

Remove a hold:
```bash
python3 -c "
import json
f = '.claude/merge-holds.json'
holds = json.load(open(f))
holds = [h for h in holds if h != 'story-NNN']
json.dump(holds, open(f, 'w'))
"
```

---

## Output policy
- Do not emit any text between tool calls. Run all tools silently.
- The only output is the final report (Step 6).

---

## Step 1: Resolve the story and worktree

**If `{{args}}` contains a story ID matching `story-\d+`:**

1. Call `pm_get_story("{{args}}")` → read the detail file to extract `db_branch`, `epic_id`, `title`, `id`
2. Compute canonical `story-branch`:
   a. If `epic_id` is non-null: call `pm_dev_branch(epic_id)` → read the detail file for `epic_slug`
      - `story-slug` = slugify(`title`): lowercase, replace spaces/non-alphanumeric with `-`, collapse consecutive `-`, truncate to 40 chars
      - `story-branch` = `<epic_slug>--<story-slug>`
   b. If `epic_id` is null or the tool returns an error: `story-branch` = `db_branch` (verbatim)
3. Run:
   ```bash
   git worktree list --porcelain
   ```
4. Find the worktree block whose `branch` line equals `refs/heads/<story-branch>`
   - If not found, also try `refs/heads/<db_branch>` (handles legacy/old-format branches)
   - If still not found, stop and report:
     > "No worktree found for branch `<story-branch>` (or legacy `<db_branch>`). Has `/run-stories` been run for this story?"
5. The `worktree` line in the matched block is `worktree-path`

**If no args (or args is empty/whitespace):**

1. Run:
   ```bash
   ls -dt .claude/worktrees/story/* 2>/dev/null | head -1
   ```
2. If output is empty, stop and report:
   > "No story worktrees found under .claude/worktrees/story/."
3. `worktree-path` = the path returned
4. Look up the actual branch checked out in that worktree by running:
   ```bash
   git worktree list --porcelain | awk '/^worktree /{wt=$2} /^branch /{if(wt=="<worktree-path>") print $2}'
   ```
   Strip the `refs/heads/` prefix to get `story-branch` (e.g., `my-feature-epic--fix-auth-flow`)
5. Try to find the story in the DB: call `pm_list_stories()` across all epics and scan for a `branch` field matching `story-branch`
6. If a DB match is found: extract `story_id`, `epic_id`, `title`
7. If no DB match: set `story_id = null`, `epic_id = null`, `title = basename of worktree-path` — proceed git-only (skip pm_update_story at the end)

**At the end of Step 1 you must have:**
- `worktree-path`: absolute path to the story worktree
- `story-branch`: e.g., `my-feature-epic--fix-auth-flow`
- `story_id` (may be null)
- `epic_id` (may be null)
- `title`: display name for commit message

```bash
bash ~/.claude/scripts/emit-event.sh "skill.merge.started" "claude" "${story_id:-unknown}" '{"branch":"'"$STORY_BRANCH"'"}'
```

> **Note:** If `branch` is null in the DB, compute the story branch from the worktree list — this is normal for stories created via `/todo` before a worktree was set up.

### Step 1.5: test_files gate

If `story_id` is null, skip this step.

Call `pm_get_story(story_id)` and check the `test_files` field.

**If `test_files` is non-empty and not "N/A":**

1. List commits on the story branch not on dev:
   ```bash
   git -C <worktree-path> log --oneline dev..<story-branch>
   ```
2. Check if any commits touch test files:
   ```bash
   git -C <worktree-path> log --oneline --diff-filter=A -- <test_files_glob>
   ```
   If no commits touch test files, emit a warning (non-blocking):
   > "Warning: story has test_files but no test file commits found on branch. The test agent may have determined no tests were needed."

**If `test_files` is "N/A":** skip this step.

**If `test_files` is empty or null:** Hard block — stop and report:
> "BLOCKED: story <story_id> has no test_files set in its plan. Every story must declare test_files (explicit paths or N/A with justification) before merging. Update the plan file and re-run."

---

## Step 2: Determine the dev branch

> Note: The dev branch is always `dev`. `pm_dev_branch` is called in Step 1 for `epic_slug` only.

Set `dev-branch` = `dev`.

**Verify the branch exists on origin:**

```bash
git fetch origin dev
```

If this fails (branch not found on origin), stop and report:
> "Dev branch `dev` does not exist on origin. Create it first."

---

## Step 2.5: Smoke test

Run build verification and tests in the story worktree before merging:

```bash
VERIFY_RESULT=$(bash ~/.claude/scripts/build-verify.sh --project-root <worktree-path>)
```

Parse the JSON result:
- `project_type` is `"unknown"` and `build_result` is `"skip"` (i.e., `--no-build` was passed) → Set `test_result = "skipped (--no-build)"`. Continue to Step 3.
- `project_type` is `"unknown"` and `build_result` is `"fail"` → Set `test_result = "FAIL"`. Stop and report: "No recognized build system in worktree. Either add a build system or pass `--no-build` to `build-verify.sh`." Do NOT proceed to merge.
- `build_result` is `"pass"` → Set `test_result = "pass"`. Continue to Step 3.
- `build_result` is `"fail"` → Set `test_result = "FAIL"`. Display the failure output from JSON. Stop and report: "Tests failed in `<worktree-path>`. Fix the failures before merging, or re-run with `--skip-tests` to bypass." Do NOT proceed to merge.

### Step 2.5b: Test validation gate (test_files stories only)

This gate prevents merging a story that bypassed run-stories validation (e.g., manual `/merge-worktree` invocation). It runs after the smoke test.

1. Check if the story has `test_files` (from `pm_get_story` data retrieved in Step 1, or call it now if not already cached).

2. If `test_files` is empty, null, or `story_id` is null — **skip this step entirely**. Existing smoke test behavior is sufficient. Stories without `test_files`, bootstrap stories, and stories from before this feature all merge exactly as before.

3. If `test_files` is non-empty:

   a. Verify the story branch contains commits touching test files:
      ```bash
      git -C <worktree-path> log --oneline --diff-filter=A -- <test_files_glob>
      ```
      If no commits touch test files, **warn but do not block**:
      > "Warning: story has test_files but no test file commits found on branch."

   b. Run tests targeting the test_files in the worktree:
      ```bash
      cd <worktree-path> && <test-command> <test_files>
      ```

   c. If tests pass:
      - Set `test_result = "pass (spec tests)"` (overrides the smoke test result)
      - Continue to Step 3.

   d. If tests fail:
      - Run test diagnosis to attribute the failure:
        ```bash
        DIAG_RESULT=$(bash ~/.claude/scripts/test-diagnosis.sh \
          --worktree-path <worktree-path> \
          --dev-branch <dev-branch> \
          --test-cmd "<test-command>" \
          --test-files "<test_files>" \
          --story-branch <story-branch>)
        ```
      - Parse the JSON `diagnosis` field and set the failure message accordingly:
        - `test_invalid` → Set `test_result = "FAIL (spec tests): test fails on dev too — test is invalid, relaunch test agent"`
        - `code_regression` → Set `test_result = "FAIL (spec tests): test passes on dev, fails on story branch — code regression, fix implementation"`
        - `inconclusive` → Set `test_result = "FAIL (spec tests): could not determine attribution — {detail from JSON}"`
      - Display the failure output and diagnosis.
      - Stop and report: "Tests failed in `<worktree-path>`. Diagnosis: {test_result}. Fix the failures before merging."
      - Do NOT proceed to merge.

### Step 2.5c: Coverage delta check (advisory)

This step runs only when `test_files` is non-empty AND spec tests passed in Step 2.5b. It is purely advisory — it never blocks the merge.

1. Detect the project type (same detection logic as `merge-gate.py`'s `detect_project_type`):
   - Check for `package.json` → Node/JS project
   - Check for `pytest.ini`, `setup.py`, `pyproject.toml` → Python project
   - Otherwise → unknown (skip silently)

2. Run coverage against the story's test files targeting write_files:
   - **Node/JS**: `cd <worktree-path> && npx c8 --reporter=text <test-command> <test_files> 2>&1 || true`
   - **Python**: `cd <worktree-path> && python -m pytest --cov=<write_files_dirs> --cov-report=term <test_files> 2>&1 || true`

3. Parse the coverage output for per-file percentages.

4. For each file in `write_files` with 0% coverage, emit a non-blocking warning:
   > "Warning: {file} has 0% test coverage"

5. If the coverage command fails, the project type is unknown, or output can't be parsed — skip silently. No warning, no block.

---

## Step 2.6: Project test suite gate

Run the project's existing test suite to catch regressions before merging. This prevents shipping code that breaks tests outside the story's scope.

1. Detect test directory:
   ```bash
   TEST_DIR=""
   for candidate in "<project-root>/.claude/.claude/tests" "<project-root>/tests" "<project-root>/test"; do
     if [ -d "$candidate" ]; then
       TEST_DIR="$candidate"
       break
     fi
   done
   ```

2. If `TEST_DIR` is empty, skip this step silently.

3. Run the test suite:
   ```bash
   python3 -m pytest "$TEST_DIR" -x -q --tb=short 2>&1
   ```

4. If pytest exits non-zero, STOP and report:
   > "Project test suite failed. Fix the failures before merging."
   Do NOT proceed to Step 3.

5. If pytest exits zero, continue to Step 3.

---

## Step 3: Merge story branch into dev

```bash
# Check if dev-branch is already the current branch in the main worktree
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" = "<dev-branch>" ]; then
  # dev branch is already checked out here — merge directly, no temp worktree needed
  git merge --no-ff <story-branch> -m "merge: <title>"
  git push origin <dev-branch>
  HASH=$(git rev-parse --short HEAD)
else
  # Create a temp worktree for the dev branch
  TEMP=$(mktemp -d /tmp/merge-dev-XXXXXX)
  git worktree add "$TEMP" <dev-branch>

  # Ensure we have the latest dev branch state (prevents stale-push failures
  # when multiple stories merge into the same dev branch sequentially)
  git -C "$TEMP" pull --rebase origin <dev-branch>

  # Merge with --no-ff for clear history
  git -C "$TEMP" merge --no-ff <story-branch> -m "merge: <title>"
fi
```

**If the merge exits non-zero (conflict):**
1. Capture and display the conflict output
2. If using temp worktree, clean it up:
   ```bash
   git worktree remove --force "$TEMP"
   ```
3. Emit merge failure event and stop:
   ```bash
   bash ~/.claude/scripts/emit-event.sh "story.merge_failed" "claude" "${story_id:-unknown}" '{"branch":"'"$STORY_BRANCH"'","reason":"conflict"}'
   ```
   > "Merge conflict while merging `<story-branch>` into `<dev-branch>`. The story worktree has NOT been removed. Resolve the conflict manually and re-run."

**If the merge succeeds (temp worktree path):**

```bash
# Push dev branch
git -C "$TEMP" push origin <dev-branch>

# Capture short commit hash for the report
HASH=$(git -C "$TEMP" rev-parse --short HEAD)

# Clean up temp worktree
git worktree remove --force "$TEMP"
```

```bash
bash ~/.claude/scripts/emit-event.sh "story.merged" "claude" "${story_id:-unknown}" '{"branch":"'"$STORY_BRANCH"'","commit":"'"$HASH"'"}'
```

---

## Step 4: Clean up story worktree and branches

```bash
CLEANUP_RESULT=$(bash ~/.claude/scripts/worktree-cleanup.sh --worktree-path <worktree-path> --branch <story-branch>)
```

Parse the JSON result:
- `status: "success"` → worktree removed, branch deleted (local + remote). Log `removed_worktree` and `removed_branch` from JSON.
- `status: "error"` → note the failure in the report but do not stop. Continue to Step 5. The error details are in the JSON `error` field.

If the cleanup reports uncommitted changes (in the JSON), include a warning in the Step 6 report.

---

## Step 5: Update story state (only if story found in DB)

> **Serialization note**: When batch mode is active, merges are coordinated through the merge queue (`merge-queue.py`). Non-conflicting stories merge concurrently; conflicting stories are serialized by write-target overlap. The queue replaces the previous strict sequential constraint. Single-story invocations bypass the queue entirely.

If `story_id` is non-null:

```
# Transition through in-progress if needed, then to done.
# Clear worktree tracking since the worktree has been removed.
# force=True makes the in-progress call safe regardless of current state
# (ready, approved, or already in-progress all succeed).
pm_update_story(story_id, state="in-progress", force=True)
pm_update_story(story_id, state="done", worktree_active=False)
```

**Epic auto-close check** (only if `epic_id` is non-null):

Call `pm_update_epic(epic_id, auto_close=True)`.

- If `closed: true`: note in the report: `Epic <epic_id> → done (all stories complete)`.
- If `closed: false`: skip. The response includes `reason` (e.g., persistent epic, remaining stories).

---

## Step 5.5: Log outcome

Determine outcome metadata:
- `agent`: from `pm_get_story(story_id)` agent field
- `model`: infer from coder launch context this session (haiku/sonnet/opus). If unknown, "unknown".
- `file_count`: from `pm_get_story(story_id)` detail file, count elements in `write_files`.
  If `write_files` is null or empty, set to "unknown".
- `complexity_bucket`: derived from `file_count`:
  - 1-2 → "small"
  - 3-5 → "medium"
  - 6+ → "large"
  - If file_count is "unknown" → "unknown"
- `cycle_time`: compute from epics.db — time between story state entering `in-progress` and
  current timestamp. **Format: decimal hours, one decimal place, no prefix symbols.**
  Examples: `2.1h`, `0.5h`, `0.0h`. Never use `~`, `<`, `>`, or minute-based formats.
  If DB timestamps are unavailable, derive from the `coder_effort` duration field
  (e.g., 90s → 0.0h, 3600s → 1.0h). If neither source exists, use `0.0h`.
- `coder_effort`: read `/tmp/coder-effort-<story_id>.json` (written by run-stories Step 5 on
  agent completion). Format as "[model] · [tokens] tokens · [calls] calls · [duration]s".
  If the file doesn't exist (story was run outside run-stories, or pre-dates this change),
  write "not captured". Delete the temp file after reading.
- `skills_list`: read `~/.claude/.claude/tracking/skill-telemetry.jsonl`, filter by current
  session_id, collect distinct skill values. If missing, use "merge-worktree".
- `friction_summary`: query `correction_groups` table in epics.db for entries related to this story.
  Format as "N: cat1, cat2" or "0 (clean)".
- `memory_list`: recall OpenMemory queries during this session's plan critique or coder prompt
  construction for this story. If any influenced a decision, list topics. Otherwise "none".

Write outcome to `~/.claude/.claude/run-state.db` (merge_outcomes table):

```python
python3 -c "
import sqlite3, os
db = os.path.expanduser('~/.claude/.claude/run-state.db')
conn = sqlite3.connect(db, timeout=10)
c = conn.cursor()
c.execute('PRAGMA journal_mode=WAL')
c.execute('PRAGMA busy_timeout=5000')
# Migrate new columns (idempotent)
for col in [
    'what_worked TEXT',
    'what_failed TEXT',
    'friction_events INTEGER DEFAULT 0',
    'file_count INTEGER',
    'complexity TEXT',
    'skills_used TEXT',
    'coder_effort TEXT',
    'memory_attributed TEXT',
]:
    try:
        c.execute(f'ALTER TABLE merge_outcomes ADD COLUMN {col}')
    except sqlite3.OperationalError:
        pass
c.execute('''INSERT OR REPLACE INTO merge_outcomes
    (story_id, epic_id, agent, model, domain_tags, success, cycle_time_s,
     revert_count, what_worked, what_failed, friction_events, file_count,
     complexity, skills_used, coder_effort, memory_attributed)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
    ('[story_id]', '[epic_id]', '[agent]', '[model]', '[skills_list]',
     True, [cycle_time_seconds], [friction_count],
     '[what_worked]', '[what_failed]', [friction_count], [file_count],
     '[complexity_bucket]', '[skills_list]', '[coder_effort]', '[memory_list]'))
conn.commit()
conn.close()
"
```

---

## Step 5.6: Post-merge regression check

> Only runs in batch mode (2+ stories merging in the same epic). Single-story merges skip this step. Only runs when `epic_id` is non-null. Runs after Step 5.5 completes.

**Procedure:**

1. Build the story manifest. For each previously merged story in the current epic (from the batch's `MERGE_SUMMARY.merged` list plus stories already merged in prior waves this session), collect `write_files`, `plan_file`, and `acceptance_criteria` from the per-story data passed to the subagent.

   Format as JSON: `{story_id: {write_files: [...], plan_file: "/path/to/plan.md", acceptance_criteria: "raw text of ## Acceptance criteria section"}}`.

2. For the just-merged story, invoke the regression check script:

   ```bash
   REGRESS_RESULT=$(python3 ~/.claude/scripts/regression-check.py \
     --epic-id <epic_id> \
     --just-merged-story-id <story_id> \
     --just-merged-write-files "<comma-separated write_files>" \
     --project-root <project-root> \
     --dev-branch <dev-branch> \
     --session-id <session_id> \
     --story-manifest '<JSON string>')
   ```

3. Parse the JSON result:
   - Exit 0 (`criteria_failed` == 0): Log "Regression check: clean (N criteria verified, M manual skipped)." Continue.
   - Exit 1 (`criteria_failed` > 0): Log the failures as warnings in the merge report. **Non-blocking** — the merge already happened. The regression is surfaced for the user to decide whether to revert or fix forward.
   - Exit 2: Log "Regression check: system error — <error>." Continue (non-blocking).

4. Include regression results in the Step 6 report and in the batch MERGE_SUMMARY `regressions` field.

---

## Step 5.7: Coder divergence capture

**Purpose:** When a coder deviates from the plan to follow actual codebase conventions, capture that as a proposed decision. This closes the loop — bootstrap catches architecture, exemplar matching catches file-level conventions, divergence capture catches everything else.

**When to run:** After each successful merge (step 5 complete, story merged to dev). Skip for blocked or failed stories.

**Procedure:**

1. For each merged story, read the plan file and extract the `## Tasks` section.

2. Read the coder agent's result (from the run-stories output or the commit message notes). Look for phrases indicating deviation:
   - "matching codebase convention despite plan"
   - "plan specified X but codebase uses Y"
   - "adapted to actual pattern"
   - "followed existing [file] pattern instead"
   - Any coder note that contradicts a plan task

3. For each divergence found, construct a proposed decision:
   ```
   Proposed decision: <what the coder actually did>
   Evidence: <story_id> plan specified <X>, coder did <Y> after reading <exemplar file>.
   Coder note: "<exact note from coder result>"
   Source: ai-discovered (post-execution divergence)
   Scope: <file or pattern scope inferred from the divergence>
   ```

4. Write proposed decisions to `<project-root>/.claude/proposed-decisions.md` (append, don't overwrite). This file is reviewed by the user — proposed decisions are NOT automatically added to decisions.sql.

   Format:
   ```markdown
   ## Proposed decision (story-NNN, <date>)

   **Convention:** <what the coder discovered>
   **Evidence:** Plan said <X>. Coder did <Y> after reading <exemplar>.
   **Scope:** <file pattern or directory>
   **Status:** pending review
   ```

5. Include proposed decision count in the Step 6 report:
   ```
   Divergences captured: N proposed decisions → .claude/proposed-decisions.md
   ```

**Why proposed, not auto-added:** A coder divergence might be correct (following real convention) or incorrect (coder made a mistake the tests didn't catch). The user must review before it becomes a recorded decision. Auto-adding would pollute decisions.sql with unvalidated patterns.

---

## Step 6: Report

Print a summary using the information collected above:

```
Merged: <story-branch> → <dev-branch>  (commit <HASH>)
Worktree removed: <worktree-path>
Branch deleted: <story-branch> (local + remote)
Tests: <test_result>
Story updated: <story_id> → done
Epic updated:   <epic_id> → done (all stories complete)   ← only if auto-closed
```

If `story_id` was null, omit the "Story updated" line and add a note:
> "Story not found in DB — state was not updated."

If any cleanup step failed, append a "Warnings" section listing each failure.

If regressions were detected (Step 5.6), append:

```
Regressions detected:
  story-MMM merge broke:
    - story-AAA: "<criterion text>" — <error> (overlap: <file1>, <file2>)
```

If all regression checks passed:

```
Regression checks: clean (N criteria verified across M stories)
```

If Step 5.6 was skipped (single-story merge or no epic_id), omit the regression section entirely.
