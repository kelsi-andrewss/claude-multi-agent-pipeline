# Plan: Branch Naming Convention Unification

## Context

The system currently has two inconsistent branch naming conventions running in parallel:

- **Script pipeline** (`setup-story.sh`, `merge-story.sh`, `merge-epic.sh`) uses:
  `epic/<epic-slug>` as the epic branch, with stories branching from it
- **Skill pipeline** (`run-stories`, `merge-worktree`) uses:
  `dev/<epic-slug>` as the staging branch, with stories branching from it

The desired unified convention is:

```
main
  └── dev                          ← stable integration branch
        └── dev/<epic-slug>        ← per-epic staging branch
              └── dev/<epic-slug>/<story-slug>   ← per-story work branch
```

Merge flow:
- Story → `dev/<epic-slug>` (story done)
- `dev/<epic-slug>` → `dev` (epic done, when confident)
- `dev` → `main` (release, when confident)

This replaces the `epic/<epic-slug>` prefix entirely. No more split between `epic/` and `dev/` naming.

---

## Critical files

| File | Change |
|---|---|
| `.claude/scripts/setup-story.sh` | Replace `epic/<slug>` with `dev/<slug>` as the parent branch; story branch becomes `dev/<slug>/<story-slug>` |
| `.claude/scripts/merge-story.sh` | Replace `epic/<slug>` target with `dev/<slug>`; update worktree path |
| `.claude/scripts/merge-epic.sh` | Replace `epic/<slug>` with `dev/<slug>`; merge target changes from `main` to `dev` |
| `skills/run-stories/SKILL.md` | Update Step 3 dev-branch creation to use `dev/<slug>`, Step 4 story-branch to `dev/<slug>/<story-slug>` |
| `skills/merge-worktree/SKILL.md` | Update Step 2 dev-branch derivation; update Step 3 merge target; story branch pattern |
| `agents/git-ops.md` | Update any branch naming references if present |

---

## Change Details

### Naming convention (new)

| Branch | Pattern | Example |
|---|---|---|
| Integration | `dev` | `dev` |
| Epic staging | `dev/<epic-slug>` | `dev/auth-overhaul` |
| Story work | `dev/<epic-slug>/<story-slug>` | `dev/auth-overhaul/add-oauth-flow` |

Slugification rule (unchanged): lowercase, replace spaces/non-alphanumeric with `-`, collapse consecutive `-`, truncate to 40 chars.

---

### `setup-story.sh`

**Args stay the same:** `<project-root> <epic-slug> <story-branch> <story-slug>`

- Line 17: `EPIC_BRANCH="epic/${EPIC_SLUG}"` → `DEV_BRANCH="dev/${EPIC_SLUG}"`
- Line 18: worktree path unchanged (already uses `${STORY_BRANCH}`)
- Lines 25-27: fetch `dev` and `dev/<slug>` instead of `main` and `epic/<slug>`
- Lines 30-35: create `dev/<slug>` from `dev` (not `main`) if it doesn't exist
- Lines 41-46: branch story from `DEV_BRANCH` (not `EPIC_BRANCH`)

Also: the `STORY_BRANCH` arg passed in will now be `dev/<epic-slug>/<story-slug>` — the caller (run-stories skill) is responsible for constructing it correctly.

---

### `merge-story.sh`

**Args:** `<project-root> <epic-slug> <story-branch> <story-title>` (drop `[<pr-number>]` — no PRs)

- Line 19: `EPIC_BRANCH="epic/${EPIC_SLUG}"` → `DEV_BRANCH="dev/${EPIC_SLUG}"`
- All references to `EPIC_BRANCH` → `DEV_BRANCH`
- Remove all PR creation/update logic (lines 59-83) — stories push directly, no GitHub PR
- Keep worktree cleanup (lines 86-93)
- Output: `MERGED:<story-branch>:DEV_BRANCH=<dev-branch>` (no PR number)

---

### `merge-epic.sh`

**New args:** `<project-root> <epic-slug>` (drop `<pr-number>` — no PRs)

- Remove `PR_NUMBER` arg and all `gh pr` logic entirely
- `EPIC_BRANCH="epic/${EPIC_SLUG}"` → `DEV_EPIC_BRANCH="dev/${EPIC_SLUG}"`
- Merge target: `dev` (not `main` via PR)
- Use a temp worktree on `dev`, merge `dev/<epic-slug>` into it with `--no-ff`, push `dev`
- Delete local and remote `dev/<epic-slug>` after merge
- Output: `MERGED:dev/<epic-slug>:into=dev`

---

### `skills/run-stories/SKILL.md`

**Step 3 (Ensure dev branches exist):**
- First ensure `dev` itself exists: `git show-ref --verify --quiet refs/heads/dev || git branch dev origin/main`
- Then create `dev/<slug>` branching from `dev` (not `origin/main`)

**Step 4 (Execute groups):**
- `story-branch`: change from `story/<story-slug>` → `dev/<epic-slug>/<story-slug>`
- `worktree-path`: stays `.claude/worktrees/story/<story-slug>` (local path only, no need to mirror branch name)
- `dev-branch`: stays `dev/<epic-slug>` (unchanged concept, just now the correct prefix)
- Story branches from `dev/<epic-slug>`, not `origin/main`

---

### `skills/merge-worktree/SKILL.md`

**Step 1:** When resolving story-slug from worktree path, `story-branch` is now `dev/<epic-slug>/<story-slug>` — update the derivation logic accordingly (read it from git worktree list, not reconstruct from basename alone).

**Step 2 (Determine the dev branch):**
- `dev-branch` = `dev/<epic-slug-from-epic_id>` (unchanged concept)
- Fallback: `dev/<epic_id>` (unchanged)
- Remove the note about `dev/<slug>` being derived from epic title — it already does this

**Step 3 (Merge):**
- Merge `dev/<epic-slug>/<story-slug>` → `dev/<epic-slug>` (not the old `dev/<slug>` ← `story/<slug>`)
- Push `dev/<epic-slug>` to origin

**Step 4 (Cleanup):**
- Delete `dev/<epic-slug>/<story-slug>` local and remote (was `story/<story-slug>`)

---

## Verification

1. Create a test epic and story in the DB → run `/run-stories` → confirm worktree is created at `.claude/worktrees/story/<story-slug>` on branch `dev/<epic-slug>/<story-slug>`

2. Run `/merge-worktree` → confirm merge target is `dev/<epic-slug>`, story branch `dev/<epic-slug>/<story-slug>` is deleted

3. Manually run `merge-epic.sh` for a test epic → confirm `dev/<epic-slug>` merges into `dev` (not `main`)

4. Confirm `setup-story.sh` no longer references `epic/` anywhere

5. Confirm `git branch -a` shows the expected `dev/`, `dev/<slug>/`, and `dev/<slug>/<story-slug>` structure
