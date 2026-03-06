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

> **Note:** If `branch` is null in the DB, compute the story branch from the worktree list — this is normal for stories created via `/todo` before a worktree was set up.

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

Run project tests in the story worktree before merging. This catches regressions early.

1. Detect test infrastructure in `<worktree-path>`:
   - `package.json` with `scripts.test` → `npm test`
   - `pytest.ini`, `pyproject.toml` with `[tool.pytest]`, or `tests/` dir with `*_test.py`/`test_*.py` → `pytest`
   - `go.mod` with `*_test.go` files → `go test ./...`
   - `Cargo.toml` → `cargo test`
   - `pubspec.yaml` with `test/` dir → `flutter test`

2. If no test infrastructure detected:
   - Set `test_result = "skipped (no infra)"`
   - Continue to Step 3.

3. If test infrastructure detected, run the test command:
   ```bash
   cd <worktree-path> && <test-command>
   ```

4. If tests pass:
   - Set `test_result = "pass"`
   - Continue to Step 3.

5. If tests fail:
   - Set `test_result = "FAIL"`
   - Display the failure output.
   - Stop and report: "Tests failed in `<worktree-path>`. Fix the failures before merging, or re-run with `--skip-tests` to bypass."
   - Do NOT proceed to merge.

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
3. Stop and report:
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

---

## Step 4: Clean up story worktree and branches

```bash
# Check for uncommitted changes before removal (informational — the merge
# already captured all committed work, but this surfaces unexpected state)
DIRTY=$(git -C <worktree-path> status --porcelain 2>/dev/null)
if [ -n "$DIRTY" ]; then
  echo "Warning: worktree has uncommitted changes that will be lost:"
  echo "$DIRTY"
fi

# Remove the story worktree
git worktree remove --force <worktree-path>
git worktree prune

# Delete local story branch
git branch -D <story-branch>

# Delete remote story branch
git push origin --delete <story-branch>
```

If any cleanup command fails, note the failure in the report but do not stop — continue to Step 5.

---

## Step 5: Update story state (only if story found in DB)

> **Serialization note**: When `/run-stories` calls `/merge-worktree` for multiple DONE
> stories in the same epic, it must call them **sequentially** — wait for each merge to
> complete before starting the next. This prevents stale-push race conditions on the dev branch.

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
- `friction_summary`: read `~/.claude/friction-log.md`, count entries matching this story_id.
  Format as "N: cat1, cat2" or "0 (clean)".
- `memory_list`: recall OpenMemory queries during this session's plan critique or coder prompt
  construction for this story. If any influenced a decision, list topics. Otherwise "none".

Append to `~/.claude/outcomes.md`:

```
## [ISO date] -- [story_id] -- [title]
**Intent**: [story title from DB]
**Result**: merged
**Agent**: [agent]
**Model**: [model]
**Cycle time**: [cycle_time]
**Coder effort**: [coder_effort]
**Skills used**: [skills_list]
**Friction events**: [friction_summary]
**Tests**: [test_result]
**File count**: [file_count]
**Complexity**: [complexity_bucket]
**Memory attributed**: [memory_list]
**What worked**: [brief — infer from merge process: clean execution, or note if escalation/restart occurred]
**What failed**: [brief — "nothing" or summarize any coder failures/restarts that preceded the merge]
```

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
