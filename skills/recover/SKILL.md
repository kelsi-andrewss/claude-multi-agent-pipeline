---
name: recover
description: >
  Cross-reference git worktree state against the DB to find and fix mismatches.
  Detects orphaned worktrees, stale DB records, and stories stuck in wrong states.
  Use when the user says "/recover", "recover", or "fix worktree state".
args: []
---

# Recover Skill Invoked

User has requested: `/recover`

---

## Output policy
- Show findings as they are discovered. This is an interactive skill — ask before mutating.

---

## Step 1: Gather state from both sources

Run these in parallel:

**Git state:**
```bash
git worktree list --porcelain
```

Parse the output into a list of worktrees. For each block:
- `worktree <path>` → the worktree path
- `branch refs/heads/<branch>` → the branch name
- Skip the main worktree (has `bare` or is the repo root)

Filter to only worktrees whose path contains `.claude/worktrees/story/`.

**DB state:**

Call `pm_list_stories()` across all active epics. For each story where `archived=0` and `state` is NOT `done` or `shipped`, collect:
- `id`, `state`, `branch`, `worktree_path`, `worktree_active`

---

## Step 2: Cross-reference and classify mismatches

Build a findings list by checking these conditions:

### 2a. DB says worktree active, but no worktree exists

For each story where `worktree_active=True` (or `worktree_active=1`):
- Check if `worktree_path` appears in the git worktree list
- If NOT found → mismatch: "story-NNN: DB says worktree active at `<path>`, but no worktree exists"
- Proposed fix: `pm_update_story(story_id, worktree_active=False)`

### 2b. Worktree exists, but DB says not active

For each git worktree under `.claude/worktrees/story/`:
- Find a story whose `branch` matches the worktree's branch
- If found and `worktree_active` is False (or null) → mismatch: "story-NNN: worktree exists at `<path>` but DB says not active"
- Proposed fix: `pm_update_story(story_id, worktree_active=True, worktree_path="<path>")`

### 2c. Story is `in-progress` but no worktree

For each story in `in-progress` state:
- Check if its branch appears in any worktree
- If NOT found → mismatch: "story-NNN is in-progress but has no worktree"
- Proposed fix: `pm_update_story(story_id, state="ready", force=True, worktree_active=False)`

### 2d. Orphaned worktrees (no matching story)

For each git worktree under `.claude/worktrees/story/`:
- Check if any story's `branch` matches the worktree's branch
- If NO match → orphan: "Orphaned worktree at `<path>` (branch: `<branch>`) — no matching story in DB"
- Proposed fix: manual `git worktree remove <path>`

---

## Step 3: Report findings

Print a summary table:

```
Recover scan complete.

Mismatches found: N

  Type                          Story       Details
  DB active, no worktree        story-NNN   worktree_path was <path>
  Worktree exists, DB inactive  story-NNN   path: <path>
  In-progress, no worktree      story-NNN   will reset to ready
  Orphaned worktree             —           path: <path>, branch: <branch>
```

If no mismatches: print "No mismatches found. Git and DB state are consistent." and stop.

---

## Step 4: Ask before fixing

If mismatches were found, ask via `AskUserQuestion`:

> "Found N mismatches. Apply all fixes?"
>
> Options:
> - "Apply all" — fix all mismatches
> - "Review individually" — ask for each one
> - "Skip" — report only, no changes

### If "Apply all":
Execute all proposed fixes (pm_update_story calls). For orphaned worktrees, list them but do NOT auto-remove — print:
> "Orphaned worktrees listed above were NOT removed. Verify no uncommitted work remains, then run `git worktree remove <path>` manually."

### If "Review individually":
For each mismatch, ask:
> "Fix: <description>? (yes/no)"
Execute only the confirmed fixes.

### If "Skip":
Stop. No mutations.

---

## Step 5: Summary

Print what was fixed:

```
Recovery complete.

Fixed:
  story-NNN: worktree_active → false
  story-NNN: worktree_active → true, worktree_path → <path>
  story-NNN: state → ready (was in-progress with no worktree)

Not fixed (manual action needed):
  Orphaned worktree: <path>
```
