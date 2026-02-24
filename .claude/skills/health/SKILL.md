---
name: health
description: >
  Check epics.json for structural issues and data inconsistencies: orphaned
  worktrees, stories stuck in merging without PRs, queued stories ready to
  unblock, duplicate epic IDs, and stories referencing non-existent epics.
  Use when the user says "/health", "check health", "epics status", or
  "any data integrity issues?". Read-only — does not modify any files.
---

# /health

Trigger: user types `/health`

## Procedure

1. **Read epics.json** from the project root (`./.claude/epics.json`).
2. **Collect worktree data** by running `git worktree list` in the project root.
   Parse output with awk: `awk '{print $1, $3}' | grep -v detached`
   to extract pairs of `<path>  <branch>` (branch in square brackets or detached).
3. **Run five health checks**:

### Check A: Orphaned Worktrees
- Parse `git worktree list` output.
- For each worktree in `.claude/worktrees/story/<slug>`:
  - Extract the story slug from the worktree path.
  - Look up the story in epics.json by matching `story/<slug>` to the story's `branch` field.
  - **Issue**: Worktree exists but story not found in epics.json, OR story is found but its `state` is `closed`.
  - **Do not flag**: Worktrees with `branch: null` (story has no worktree yet — expected).

### Check B: Stories Stuck in Merging
- Scan all stories where `state == "merging"`.
- For each, check the parent epic's `prNumber` field.
- **Issue**: Story is in `merging` state AND epic's `prNumber` is `null` AND the story actually has a non-null `branch`.
  - Flag as "possibly stuck" (the PR may exist but prNumber wasn't recorded yet; confirm manually).
- **Do not flag**: stories with `branch: null` (they have no worktree to stick).

### Check C: Queued Stories Ready to Unblock
- Scan all stories where `state == "queued"`.
- For each, check its `dependsOn` array.
- **Issue**: ALL story IDs in `dependsOn` have `state: "closed"`. This story is ready to auto-launch.
- **Report**: "Queued story [id] ([title]) — all blockers closed, ready to run: [blocked by ids]"

### Check D: Duplicate Epic IDs
- Scan all epics in epics.json.
- **Issue**: Two epics have the same `id` field.
- **Report**: "Duplicate epic ID: [id] appears in [count] epics"

### Check E: Stories Referencing Non-Existent Epics
- For each story, check its `epicId` field.
- Look up the epic by ID in the epics array.
- **Issue**: Story's `epicId` does not match any epic's `id`.
- **Report**: "Story [id] ([title]) references non-existent epic: [epicId]"

## Output format

Print each category in order. Omit categories with no issues (print "No issues" for that category).

```
# epics.json Health Check

## A. Orphaned Worktrees
[list any issues, or "No issues"]

## B. Stories Stuck in Merging
[list any issues, or "No issues"]

## C. Queued Stories Ready to Unblock
[list any issues, or "No issues"]

## D. Duplicate Epic IDs
[list any issues, or "No issues"]

## E. Stories Referencing Non-Existent Epics
[list any issues, or "No issues"]

## Summary
[count] issues found.
```

For each issue, print a one-line summary with story/epic ID, title (if applicable), and the specific problem.

## Implementation notes

- Use `python3` or `jq` to parse epics.json (jq is preferred for reliability).
- Parse `git worktree list` output with awk/grep; the format is:
  ```
  /path/to/worktree  abc123def  [branch-name]
  ```
  Each line has `<path>  <commit>  [<branch>]` or `<path>  <commit>  (detached)`.
- For worktree orphan detection, extract the story slug from `.claude/worktrees/story/<slug>` by capturing everything after the last `/`.
- Match the slug against each story's `branch` field (which has format `story/<slug>`).
- When a story has `state: "queued"`, check all story IDs in its `dependsOn` array — if ALL are `closed`, flag it as ready.
- Do NOT read any other files. This is pure data consistency checking.
