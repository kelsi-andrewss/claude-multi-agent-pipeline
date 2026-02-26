---
name: quickfix
description: >
  Lighter-than-/todo path for 1-3 file fixes with known root cause. Uses a
  worktree and background coder but skips orchestrator and epics.json tracking.
  Merges via auto-squashed PR. Supports --test flag for testable files.
args:
  - name: description
    type: string
    description: "What to fix and which files (e.g. 'fix drag offset in src/handlers/dragHandler.js, src/components/DragPreview.jsx')"
---

# /quickfix — Lightweight multi-file fix

See ORCHESTRATION.md section 21 for qualification rules and policy.

## Step 1: Parse

Extract file paths (1-3) and fix description from `{{description}}`.
If file paths are ambiguous, ask the user.

## Step 2: Qualification gate

ALL must pass — reject and suggest `/todo` if any fail:

1. **1-3 files** and all exist
2. **Not edit-protected**: Check `<project>/.claude/protected-files.md` (edit-protected section). Fallback: check ORCHESTRATION.md protected Konva list
3. **Testable file check**: If any file is in `src/utils/`, `src/hooks/`, or has a `.test.*` counterpart → ask user, set `needsTesting = true`
4. **No schema/frame/AI tool changes**
5. **Dedup**: No `in-progress` or `draft` story in `epics.json` has any of these files in `writeFiles`

If gate fails, print which condition failed and suggest `/todo`.

## Step 3: Summary + confirm

Print:
```
Quickfix: <description>
Files: <list>
Testing: <yes if needsTesting, otherwise no>
```
Ask user to confirm.

## Step 4: Branch + worktree

Create the branch without checking it out in the main worktree, then add as a worktree:
```bash
git branch quickfix/<slug> origin/main
git worktree add <project-root>/.claude/worktrees/quickfix/<slug> quickfix/<slug>
```

Symlink `.env` and `node_modules` into the worktree if they exist at project root:
```bash
ln -sf <project-root>/.env <project-root>/.claude/worktrees/quickfix/<slug>/.env
ln -sf <project-root>/node_modules <project-root>/.claude/worktrees/quickfix/<slug>/node_modules
```

The main worktree branch MUST NOT change. If it does, something went wrong — stop and report.

## Step 5: Launch coder

Launch **quick-fixer** agent (background, Haiku) with:
- Write-target files (absolute paths in worktree)
- Fix description
- Relevant pitfalls from `<project>/.claude/project-orchestration.md` (fall back to global refs if not present)
- Worktree enforcement block (required — copy verbatim):
  ```
  WORKTREE: <project-root>/.claude/worktrees/quickfix/<slug>
  All file reads and writes MUST use paths under this directory.
  Before doing anything else, verify: run `git -C <worktree-path> branch --show-current`
  and confirm it prints `quickfix/<slug>`. If it prints anything else, STOP and report.
  Do NOT commit or edit files outside this worktree.
  ```
- Return length cap: 1 line on success, uncapped on error

## Step 6: Diff gate (inline)

When coder completes:
```bash
git -C <worktree-path> diff --name-only HEAD
```
Verify only declared write-target files were changed. If out-of-scope files exist:
```bash
git -C <worktree-path> checkout HEAD -- <out-of-scope-file>
git -C <worktree-path> commit -m "fix: restore out-of-scope files"
```

## Step 7: Build

```bash
cd <worktree-path> && npm run build
```
Must pass. On failure: print error, do not proceed.

## Step 8: Testing (conditional)

If `needsTesting` is true:
- Launch **unit-tester** agent (background) with write-target paths and worktree path
- Wait for result
- PASS → continue
- FAIL (trivial) → fix inline, re-run
- FAIL (non-trivial) → report to user, stop

## Step 9: Commit + PR + merge

```bash
cd <worktree-path>
git add <files>
git commit -m "<commit message>"
git push -u origin quickfix/<slug>
gh pr create --base main --title "<title>" --body "<body>"
gh pr merge --squash --delete-branch
```

## Step 10: Cleanup

```bash
git worktree remove .claude/worktrees/quickfix/<slug>
git branch -d quickfix/<slug>
```

Append entry to `<project>/.claude/hotfix-log.md`:
```
## [ISO date] — quickfix/<slug>
Files: <list>
Description: <description>
Lines changed: <N>
Testing: <yes/no>
```

## Guardrails

- **Frequency cap**: Warn (don't block) after 2 quickfixes in a single session
- **Audit**: Every quickfix is logged to `hotfix-log.md`
- **No protected files**: Hard block, no override
- **Max 3 files**: Hard block, suggests /todo
- **Testable files**: Must be acknowledged by user
