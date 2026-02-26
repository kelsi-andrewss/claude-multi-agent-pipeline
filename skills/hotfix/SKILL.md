---
name: hotfix
description: >
  Fastest pipeline path for single-file, non-protected, known-root-cause fixes
  of <=30 lines. Edits inline on a temp branch, merges via auto-squashed PR.
  Use when the user says "/hotfix", "hotfix: ...", or for trivial one-file fixes.
args:
  - name: description
    type: string
    description: "What to fix and in which file (e.g. 'fix button color in src/components/Toolbar.jsx')"
---

# /hotfix — Single-file fast lane

See ORCHESTRATION.md section 20 for qualification rules and policy.

## Step 1: Parse

Extract the target file path and fix description from `{{description}}`.
If no file path is evident, ask the user.

## Step 2: Qualification gate

ALL must pass — reject and suggest `/quickfix` or `/todo` if any fail:

1. **Exactly 1 file** and it exists
2. **Not edit-protected**: Check `<project>/.claude/protected-files.md` (edit-protected section). Fallback: check ORCHESTRATION.md protected Konva list
3. **Not test-required**: Not in `src/utils/`, `src/hooks/`, no `.test.*` counterpart
4. **No schema/frame/AI tool changes**
5. **Dedup**: No `in-progress` or `draft` story in `epics.json` has this file in `writeFiles`

If gate fails, print which condition failed and suggest the appropriate alternative.

## Step 3: Summary + confirm

Print:
```
Hotfix: <description>
File: <absolute path>
```
Ask user to confirm. Skip confirmation if `--yes` was passed in description.

## Step 4: Branch

```bash
git checkout -b hotfix/<slug> main
```
Where `<slug>` is kebab-case derived from the description (<=5 words).

## Step 5: Write sentinel

```bash
echo "<absolute file path>" > /tmp/hotfix-active
```
This allows the guard-direct-edit hook to permit the edit.
Do NOT use `$$` or any PID suffix — the hook reads `/tmp/hotfix-active` exactly.

## Step 6: Edit

Use the Edit tool to make the fix inline. The main session performs the edit directly — no coder agent.

## Step 7: Post-edit check

```bash
git diff --stat
```
If total lines changed > 30, abort:
```
Hotfix aborted: change exceeds 30 lines (<N> lines changed).
Use /quickfix for larger fixes.
```
Clean up: `git checkout main && git branch -d hotfix/<slug> && rm -f /tmp/hotfix-active`

## Step 8: Build

Run `npm run build` (foreground). Must pass. On failure: print error, do not proceed.

## Step 9: Commit

```bash
git add <file>
git commit -m "<commit message>"
```

## Step 10: PR + merge

```bash
git push -u origin hotfix/<slug>
gh pr create --base main --title "<title>" --body "<body>"
gh pr merge --squash --delete-branch
```

## Step 11: Cleanup

```bash
git checkout main
git pull
rm -f /tmp/hotfix-active
```

Append entry to `<project>/.claude/hotfix-log.md`:
```
## [ISO date] — hotfix/<slug>
File: <path>
Description: <description>
Lines changed: <N>
```

## Guardrails

- **Frequency cap**: Warn (don't block) after 3 hotfixes in a single session
- **Audit**: Every hotfix is logged to `hotfix-log.md`
- **No protected files**: Hard block, no override
- **No >30 lines**: Hard block after edit, suggests /quickfix
