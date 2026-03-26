# Single Story Merge

## Step 1: Resolve the story and worktree

**If `{{args}}` contains `story-\d+`:**
1. Call `pm_get_story("{{args}}")` → read detail file for `db_branch`, `epic_id`, `title`, `id`
2. Compute `story-branch`:
   a. If `epic_id` non-null: call `pm_dev_branch(epic_id)` → read `epic_slug`
      - `story-slug` = slugify(title): lowercase, replace non-alphanumeric with `-`, truncate 40 chars
      - `story-branch` = `<epic_slug>--<story-slug>`
   b. If `epic_id` null: `story-branch` = `db_branch` verbatim
3. Run `git worktree list --porcelain`
4. Find worktree block where `branch` = `refs/heads/<story-branch>` (also try `db_branch` for legacy)
5. Not found → stop: "No worktree found for branch."

**If no args:**
1. `ls -dt .claude/worktrees/story/* 2>/dev/null | head -1`
2. Empty → stop: "No story worktrees found."
3. Look up branch from `git worktree list --porcelain`
4. Try DB match via `pm_list_stories()`. If found: extract `story_id`, `epic_id`, `title`. If not: proceed git-only.

**Must have:** `worktree-path`, `story-branch`, `story_id` (may be null), `epic_id` (may be null), `title`.

```bash
bash ~/.claude/scripts/emit-event.sh "skill.merge.started" "claude" "${story_id:-unknown}" '{"branch":"'"$STORY_BRANCH"'"}'
```

### Step 1.5: test_files gate

Skip if `story_id` null. Check `test_files` from `pm_get_story`:
- Non-empty, not "N/A": check for test file commits. Warn if none found (non-blocking).
- "N/A": skip.
- Empty/null: BLOCK — "story has no test_files set."

## Step 2: Determine dev branch

`dev-branch` = `dev`. Verify: `git fetch origin dev`. Fails → stop.

## Step 2.5–2.6: Testing gates

Read [testing.md](testing.md) for smoke test, test validation, coverage, and project test suite gates.

## Step 3: Merge story branch into dev

```bash
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" = "<dev-branch>" ]; then
  git merge --no-ff <story-branch> -m "merge: <title>"
  git push origin <dev-branch>
  HASH=$(git rev-parse --short HEAD)
else
  TEMP=$(mktemp -d /tmp/merge-dev-XXXXXX)
  git worktree add "$TEMP" <dev-branch>
  git -C "$TEMP" pull --rebase origin <dev-branch>
  git -C "$TEMP" merge --no-ff <story-branch> -m "merge: <title>"
fi
```

**Conflict:** capture output, clean up temp worktree, emit failure event, stop.
**Success (temp worktree):**
```bash
git -C "$TEMP" push origin <dev-branch>
HASH=$(git -C "$TEMP" rev-parse --short HEAD)
git worktree remove --force "$TEMP"
```

## Step 4: Clean up

```bash
CLEANUP_RESULT=$(bash ~/.claude/scripts/worktree-cleanup.sh --worktree-path <worktree-path> --branch <story-branch>)
```

Parse JSON. Error → note in report, continue.

## Step 5: Update story state

If `story_id` non-null:
```
pm_update_story(story_id, state="in-progress", force=True)
pm_update_story(story_id, state="done", worktree_active=False)
```

**Epic auto-close:** If `epic_id` non-null: `pm_update_epic(epic_id, auto_close=True)`.

## Steps 5.5–5.7: Post-merge

Read [outcome.md](outcome.md) for outcome logging, regression check, and divergence capture.

## Step 6: Report

```
Merged: <story-branch> → <dev-branch>  (commit <HASH>)
Worktree removed: <worktree-path>
Branch deleted: <story-branch> (local + remote)
Tests: <test_result>
Story updated: <story_id> → done
Epic updated: <epic_id> → done (all stories complete)   ← only if auto-closed
```

Omit "Story updated" if `story_id` null. Append warnings if any cleanup failed. Append regression results if applicable.
