# Plan: Fix Divergent Branch Pipeline Problem

## Context

When a user runs `git pull origin main` in their project repo, git reports "You have divergent branches." This is caused by the pipeline scripts creating or operating on the local `main` ref in ways that cause it to drift from `origin/main`:

1. **`setup-story.sh` line 29**: Creates the epic branch from local `main` without first syncing it from origin. If local `main` is behind, the epic branch roots from a stale commit.
2. **`merge-epic.sh` lines 38–43**: After the squash-merge lands on origin via `gh pr merge`, the script may `git checkout main` but never runs `git pull` or `git reset --hard origin/main`. Local `main` stays on whatever commit it was before the merge.
3. **`diff-gate.sh` line 29**: Fetches origin (updates `origin/main` remote-tracking ref) but never advances local `main`. Epic branch rebase uses the stale local epic ref, which is rooted in stale `main`.

The net effect: every epic merge advances `origin/main` but local `main` never moves. Over time local `main` diverges, and `git pull origin main` fails because git doesn't know whether to merge or rebase.

## Fix

Three targeted changes to the canonical scripts in `~/.claude/.claude/scripts/`, then copy to the three project copies (week1, openemr, advocate).

### 1. `setup-story.sh` — sync main before creating epic branch

**Where**: Lines 25–30 (epic branch creation block)

Before `git branch "$EPIC_BRANCH" main`, add:
```bash
# Sync local main to origin before branching
git fetch origin main > /dev/null 2>&1 || true
git update-ref refs/heads/main origin/main 2>/dev/null || true
```

`git update-ref` advances the local `main` ref to match `origin/main` without requiring a checkout. Safe even when `main` is not the current branch.

### 2. `merge-epic.sh` — advance local main after squash-merge

**Where**: After line 28 (`git fetch origin main`), before line 29 (the log check)

Add:
```bash
git update-ref refs/heads/main origin/main 2>/dev/null || true
```

This makes local `main` match `origin/main` immediately after the squash-merge lands, so subsequent `git pull` is always a clean fast-forward (or no-op).

Also remove the `git checkout main` block (lines 37–38) entirely. The script only checks out main to switch away from the epic branch before deleting it. Replace with:
```bash
if [ "$CURRENT" = "$EPIC_BRANCH" ]; then
  git symbolic-ref HEAD refs/heads/main
fi
```
This moves HEAD to `main` without doing a working-tree checkout, which is safe in the main worktree and avoids triggering any divergent-branch logic.

### 3. `diff-gate.sh` — update local main after fetch

**Where**: After line 29 (`git fetch origin ...`)

Add:
```bash
git update-ref refs/heads/main origin/main 2>/dev/null || true
```

This ensures that when `setup-story.sh` was called earlier in the session from a stale state, the epic branch still gets a clean rebase base.

## Files to modify

| File (canonical) | Lines touched | Change |
|---|---|---|
| `~/.claude/.claude/scripts/setup-story.sh` | 25–30 | fetch + update-ref before branch creation |
| `~/.claude/.claude/scripts/merge-epic.sh` | 28–38 | update-ref after fetch; replace checkout with symbolic-ref |
| `~/.claude/.claude/scripts/diff-gate.sh` | 29 | update-ref after fetch |

Then copy each fixed file to:
- `/Users/kelsiandrews/gauntlet/week1/.claude/scripts/`
- `/Users/kelsiandrews/gauntlet/openemr/.claude/scripts/`
- `/Users/kelsiandrews/gauntlet/advocate/.claude/scripts/`

## What is NOT changed

- `merge-story.sh` — never touches local `main`, no fix needed
- `merge-queue.sh` — orchestration only, inherits fixes from diff-gate and merge-story
- `update-epics.sh` — JSON only, no git
- The `git pull.rebase` config — that's user-level; scripts should not configure global git settings

## Verification

1. Run setup-story.sh on a project where local `main` is intentionally stale; confirm epic branch roots from `origin/main`.
2. After a `gh pr merge --squash`, confirm `git log main -1` and `git log origin/main -1` show the same commit without running `git pull`.
3. Run `git pull origin main` in the project — should fast-forward or report "Already up to date." Never "divergent branches."
