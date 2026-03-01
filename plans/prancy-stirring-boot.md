# Plan: Fix systemic git errors across skills and scripts

## Context

The pipeline has been producing repeated git errors across multiple skill paths:
- Worktrees orphaned when scripts fail mid-execution
- Rebase leaving worktrees in `rebase-in-progress` state with no recovery
- merge-story.sh creates temp epic worktree that's never cleaned up on merge failure
- merge-epic.sh doesn't restore original branch if user wasn't on the epic branch
- quickfix/SKILL.md leaves orphaned worktrees + symlinks on build/test failure
- diff-gate.sh push errors silently swallowed (`|| true`), leaving remote stale
- merge-story.sh PR number extraction produces empty string on failure with no guard
- awk parsing of `git worktree list --porcelain` in merge-story.sh is fragile

The root cause is that scripts use `set -e` for early exit but have no `trap ERR` to clean up partial state, and skills don't specify cleanup steps in their failure paths.

## Files to change

### Scripts (`.claude/.claude/scripts/`)
1. `diff-gate.sh` — add `trap` to abort rebase on failure; remove `|| true` on push
2. `merge-story.sh` — add `trap` to clean up temp epic worktree on failure; guard empty FINAL_PR
3. `setup-story.sh` — add `trap` to remove partially-created worktree on failure
4. `merge-epic.sh` — capture and restore original branch; verify PR merge before branch delete

### Skills (`skills/`)
5. `quickfix/SKILL.md` — add explicit cleanup steps for build failure, test failure, and coder crash
6. `merge-story/SKILL.md` — add note: check merge-queue exit code before running cleanup

---

## Changes in detail

### 1. `diff-gate.sh` — trap rebase failure

**Problem**: `git rebase` fails → `set -e` exits → worktree left in `REBASE_HEAD` state. Next run fails immediately.

**Fix**: Add trap before rebase that runs `git rebase --abort` on any error exit:

```bash
# Before the rebase line:
cleanup_rebase() {
  git -C "$WORKTREE_PATH" rebase --abort 2>/dev/null || true
}
trap cleanup_rebase ERR

git -C "$WORKTREE_PATH" rebase "$EPIC_BRANCH"

trap - ERR  # clear trap after rebase succeeds
```

**Also fix**: Remove `|| true` from push line — if push fails, it should be reported, not swallowed:
```bash
# Before (silent failure):
git -C "$WORKTREE_PATH" push --force-with-lease origin "$STORY_BRANCH" 2>/dev/null || true

# After (fails loudly):
git -C "$WORKTREE_PATH" push --force-with-lease origin "$STORY_BRANCH"
```

---

### 2. `merge-story.sh` — trap temp worktree cleanup + guard empty PR

**Problem A**: `git merge --no-ff` inside temp epic worktree fails → `set -e` exits → `TEMP_EPIC_WORKTREE` never removed.

**Fix**: Add trap immediately after `git worktree add` for temp worktree:

```bash
if [ -n "$TEMP_EPIC_WORKTREE" ]; then
  git worktree add "$TEMP_EPIC_WORKTREE" "$EPIC_BRANCH"
  # Trap: always remove temp worktree on exit
  trap 'git worktree remove --force "$TEMP_EPIC_WORKTREE" 2>/dev/null || true' EXIT
  MERGE_DIR="$TEMP_EPIC_WORKTREE"
fi
```

Clear the trap after the temp worktree is manually removed (line 54):
```bash
git worktree remove --force "$TEMP_EPIC_WORKTREE" 2>/dev/null || true
trap - EXIT
```

**Problem B**: If `gh pr create` fails, `$FINAL_PR` is empty → output line is `MERGED:<branch>:PR_NUMBER=` → main session can't parse it.

**Fix**: Guard after PR creation:
```bash
FINAL_PR=$(gh pr create ... --json number --jq '.number' 2>/dev/null)
if [ -z "$FINAL_PR" ] || [ "$FINAL_PR" = "null" ]; then
  echo "ERROR: failed to create epic PR for ${EPIC_BRANCH}" >&2
  exit 1
fi
```

---

### 3. `setup-story.sh` — trap partial worktree on failure

**Problem**: If `git worktree add` fails partway (e.g. disk full, stale lock), `set -e` exits leaving a partial directory that blocks future `git worktree add` calls.

**Fix**: Add trap after worktree add attempt:
```bash
git worktree add -b "$STORY_BRANCH" "$WORKTREE_PATH" "$EPIC_BRANCH"
# If anything after this fails, clean up the worktree
trap 'git worktree remove --force "$WORKTREE_PATH" 2>/dev/null || true; git branch -D "$STORY_BRANCH" 2>/dev/null || true' ERR
```

Clear trap at end of script (success path):
```bash
trap - ERR
```

---

### 4. `merge-epic.sh` — capture and restore original branch

**Problem**: Script only switches away from epic branch if currently on it (`CURRENT == EPIC_BRANCH`). If user was on `main` or another branch, no restoration happens — but `gh pr merge` + `git checkout -` may still silently switch HEAD.

**Fix**: Capture original branch at the top, restore unconditionally at the end:

```bash
ORIGINAL_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")

# ... existing merge + branch delete logic ...

# At end, restore if we moved:
if [ -n "$ORIGINAL_BRANCH" ] && [ "$(git symbolic-ref --short HEAD 2>/dev/null)" != "$ORIGINAL_BRANCH" ]; then
  git checkout "$ORIGINAL_BRANCH" 2>/dev/null || true
fi
echo "Main worktree restored to: ${ORIGINAL_BRANCH:-detached}"
```

Also: verify merge succeeded before deleting local branch:
```bash
gh pr merge --squash --delete-branch "$PR_NUMBER"
# Verify the merge landed on main
git fetch origin main
MERGE_CHECK=$(git log origin/main --oneline -1)
echo "Post-merge main HEAD: $MERGE_CHECK"
```

---

### 5. `quickfix/SKILL.md` — explicit failure cleanup

**Problem**: Steps 7 (build fail) and 8 (test fail non-trivial) say "do not proceed" but don't say to remove the worktree. Orphaned worktrees accumulate.

**Fix**: Add cleanup instructions to each failure path:

In Step 7 (build failure):
```
On failure: print error, then clean up:
  git worktree remove --force <worktree-path>
  git branch -D quickfix/<slug>
Do not proceed.
```

In Step 8 (non-trivial test failure):
```
FAIL (non-trivial): report to user, then clean up:
  git worktree remove --force <worktree-path>
  git branch -D quickfix/<slug>
Stop.
```

Also add cleanup for symlinks in cleanup note:
```
rm -f <worktree-path>/.env <worktree-path>/node_modules
```

---

### 6. `merge-story/SKILL.md` — validate merge-queue exit before cleanup

**Problem**: Step 6 cleanup (branch delete, worktree prune) runs regardless of whether merge-queue.sh succeeded. If merge-queue failed partway, cleanup masks the error.

**Fix**: In step 6, explicitly check exit code:
```
6. **On exit 0 only**: run branch cleanup (step 6a).
   On non-zero exit: report full stdout/stderr to user. Do NOT run cleanup.
   The story branch and worktree remain intact for investigation.
```

---

## Verification

1. `diff-gate.sh`: simulate rebase conflict → worktree should NOT be in `REBASE_HEAD` state after script exits
2. `merge-story.sh`: kill script during merge → `_epic-merge-*` temp worktree should not exist afterward
3. `setup-story.sh`: run with a path that fails → no orphaned `.claude/worktrees/story/` directory
4. `merge-epic.sh`: run while on `main` → still on `main` after completion
5. `quickfix/SKILL.md`: fail a build → confirm skill output includes worktree cleanup instructions
6. `merge-story/SKILL.md`: confirm step 6 now gates cleanup on exit 0
