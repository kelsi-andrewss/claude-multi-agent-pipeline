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

---

## Step 1: Resolve the story and worktree

**If `{{args}}` contains a story ID matching `story-\d+`:**

1. Call `pm_get_story("{{args}}")` → extract `branch`, `epic_id`, `title`, `id`
2. Run:
   ```bash
   git worktree list --porcelain
   ```
3. Find the worktree block whose `branch` line equals `refs/heads/<branch>`
4. The `worktree` line in that block is `worktree-path`
5. If no worktree found for that branch, stop and report:
   > "No worktree found for branch `<branch>`. Has `/run-stories` been run for this story?"

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
   Strip the `refs/heads/` prefix to get `story-branch` (e.g., `dev/my-feature-epic/fix-auth-flow`)
5. Try to find the story in the DB: call `pm_list_stories()` across all epics and scan for a `branch` field matching `story-branch`
6. If a DB match is found: extract `story_id`, `epic_id`, `title`
7. If no DB match: set `story_id = null`, `epic_id = null`, `title = basename of worktree-path` — proceed git-only (skip pm_update_story at the end)

**At the end of Step 1 you must have:**
- `worktree-path`: absolute path to the story worktree
- `story-branch`: e.g., `dev/my-feature-epic/fix-auth-flow`
- `story_id` (may be null)
- `epic_id` (may be null)
- `title`: display name for commit message

---

## Step 2: Determine the dev branch

**If `epic_id` is non-null:**

1. Call `pm_get_epic(epic_id)` → get `title` as `epic-title`
2. Slugify `epic-title`:
   - lowercase
   - replace spaces and non-alphanumeric characters with `-`
   - collapse consecutive `-` into one
   - truncate to 40 characters
3. `dev-branch` = `dev/<slug>`  (e.g., `dev/my-feature-epic`)
4. Fallback if `epic-title` is missing or empty: `dev-branch` = `dev/<epic_id>` (e.g., `dev/epic-007`)

**If `epic_id` is null (git-only mode):**

1. Run:
   ```bash
   git branch -r | grep 'origin/dev/' | head -5
   ```
2. Ask the user which dev branch to merge into using `AskUserQuestion`, listing the candidates. If no `dev/` branches exist, stop and report:
   > "No dev/ branches found. Cannot determine merge target."

**Verify the branch exists on origin:**

```bash
git fetch origin <dev-branch>
```

If this fails (branch not found on origin), stop and report:
> "Dev branch `<dev-branch>` does not exist on origin. Create it first or run `/run-stories` for this epic."

---

## Step 3: Merge story branch into dev

```bash
# Create a temp worktree for the dev branch
TEMP=$(mktemp -d /tmp/merge-dev-XXXXXX)
git worktree add "$TEMP" <dev-branch>

# Merge with --no-ff for clear history
git -C "$TEMP" merge --no-ff <story-branch> -m "merge: <title>"
```

**If the merge exits non-zero (conflict):**
1. Capture and display the conflict output
2. Clean up the temp worktree:
   ```bash
   git worktree remove --force "$TEMP"
   ```
3. Stop and report:
   > "Merge conflict while merging `<story-branch>` into `<dev-branch>`. The story worktree has NOT been removed. Resolve the conflict manually and re-run."

**If the merge succeeds:**

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

If `story_id` is non-null:

```
pm_update_story(story_id, state="done")
```

---

## Step 6: Report

Print a summary using the information collected above:

```
Merged: <story-branch> → <dev-branch>  (commit <HASH>)
Worktree removed: <worktree-path>
Branch deleted: <story-branch> (local + remote)
Story updated: <story_id> → done
```

If `story_id` was null, omit the "Story updated" line and add a note:
> "Story not found in DB — state was not updated."

If any cleanup step failed, append a "Warnings" section listing each failure.
