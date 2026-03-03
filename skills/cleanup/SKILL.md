---
name: cleanup
description: >
  Archive specific stories or epics by ID, delete merged git branches, and prune
  stale worktrees. Use when the user says "/cleanup", "/cleanup story-NNN",
  "/cleanup epic-NNN", "/cleanup git", or "/cleanup all".
args:
  - name: args
    type: string
    description: >
      Optional. One or more space-separated tokens: story-NNN IDs, epic-NNN IDs,
      "git" (git-only cleanup), "all" (bulk archive + git), or empty (status report).
---

# Cleanup Skill Invoked

User has requested: `/cleanup {{args}}`

---

## Step 1: Parse args

Inspect `{{args}}` (trim whitespace):

- **Empty or whitespace** → **Status mode**: dry-run report only, no mutations. Skip to Step 5 (status report).
- `git` → **Git cleanup** only. Skip to Step 4.
- `all` → **Bulk archive** then **Git cleanup**. Run `pm_housekeep(mode="cleanup")` then Step 4.
- One or more tokens matching `story-\d+` → **Story archive** mode. Run Step 2 for each.
- One or more tokens matching `epic-\d+` → **Epic close** mode. Run Step 3 for each.
- Mixed `story-NNN` and `epic-NNN` → Run Step 2 for stories, Step 3 for epics.

Collect results from each step into tracking vars:
- `archived_stories` = []
- `closed_epics` = []
- `deleted_branches` = []
- `removed_worktrees` = []
- `orphaned_worktrees` = []

---

## Step 2: Story archive mode

For each `story-NNN` in the parsed story IDs:

1. Call `pm_get_story(story_id)` → extract `state`, `branch`, `title`, `epic_id`.
2. If `state` is already `archived` (or `archived=1`): note "already archived — skipping". Skip remaining sub-steps for this story.
3. Otherwise: call `pm_update_story(story_id, state="done", force=True)`.
4. Run `git worktree list --porcelain`. Find the block whose `branch` line equals `refs/heads/<branch>`.
   - **If found and clean** (run `git -C <worktree-path> status --porcelain` → empty output):
     - Run `git worktree remove --force <worktree-path>` then `git worktree prune`.
     - Add `<worktree-path>` to `removed_worktrees`.
   - **If found and dirty**: ask via `AskUserQuestion`:
     > "Worktree for `<title>` (`<worktree-path>`) has uncommitted changes. Remove it anyway?"
     - On yes: `git worktree remove --force <worktree-path>`, add to `removed_worktrees`.
     - On no: note "worktree kept — uncommitted changes".
   - **If not found**: no action.
5. Delete remote branch if it exists:
   ```bash
   git push origin --delete <branch> 2>/dev/null || true
   ```
   If branch was non-empty and deletion was attempted, add `<branch>` to `deleted_branches`.
6. Add `story-NNN "<title>"` to `archived_stories`.

---

## Step 3: Epic close mode

For each `epic-NNN` in the parsed epic IDs:

1. Call `pm_get_epic(epic_id)` → extract `title`, `state`.
2. Compute `epic-slug`: lowercase title, replace spaces and non-alphanumeric chars with `-`, collapse consecutive `-`, truncate to 40 chars.
3. Call `pm_list_stories(epic_id=epic_id)` → get all stories.
4. For each story not yet in a terminal state (`done`, `shipped`, `archived`):
   - Call `pm_update_story(story_id, state="done", force=True)`.
   - Add to `archived_stories`.
5. Call `pm_update_epic(epic_id, state="done")`.
6. Delete epic dev branch on remote:
   ```bash
   git push origin --delete dev/<epic-slug> 2>/dev/null || true
   ```
   Add `dev/<epic-slug>` to `deleted_branches` if the slug was non-empty.
7. Add `epic-NNN "<title>"` to `closed_epics`.

---

## Step 4: Git cleanup

```bash
# Fetch latest and prune deleted remote refs
git fetch origin --prune

# Find dev/* remote branches fully merged into origin/dev
git branch -r --merged origin/dev | grep 'origin/dev/' | grep -v 'origin/dev$'
```

For each merged remote branch returned:
- Strip `origin/` prefix → local name (e.g., `dev/my-feature`)
- Delete remote: `git push origin --delete <local-name> 2>/dev/null || true`
- Delete local if it exists: `git branch -D <local-name> 2>/dev/null || true`
- Add `<local-name>` to `deleted_branches`.

Then prune stale worktree metadata:
```bash
git worktree prune
git worktree list --porcelain
```

For any remaining worktrees whose path is under `.claude/worktrees/story/`:
- Check if the branch still exists on origin:
  ```bash
  git ls-remote --heads origin <branch> 2>/dev/null
  ```
- If empty (branch gone from remote): add path to `orphaned_worktrees` — do NOT auto-remove.

---

## Step 5: Report

### Status mode (no args)

Run `pm_housekeep(mode="cleanup", confirmed=False)` for a dry-run summary.

Then run:
```bash
git fetch origin --prune
git branch -r --merged origin/dev | grep 'origin/dev/' | grep -v 'origin/dev$'
git worktree list --porcelain
```

Print a read-only status report:
```
Cleanup status (dry run — no changes made):

Archivable stories:  <pm_housekeep dry-run output>
Merged dev/* branches: <list or "none">
Potentially orphaned worktrees: <list or "none">

Run /cleanup all to archive stale stories and prune merged branches.
Run /cleanup story-NNN or epic-NNN to target specific items.
Run /cleanup git to prune branches and worktrees only.
```

### After mutations

Print a summary table:

```
Cleanup complete.

Stories archived:   <archived_stories list, or "none">
Epics closed:       <closed_epics list, or "none">
Branches deleted:   <deleted_branches list, or "none">
Worktrees removed:  <removed_worktrees list, or "none">
Orphaned worktrees: <orphaned_worktrees list with note, or "none">
```

If `orphaned_worktrees` is non-empty, append:
> "Orphaned worktrees were not removed automatically — verify no uncommitted work remains, then run `git worktree remove <path>` manually."
