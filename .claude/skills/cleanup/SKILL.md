---
name: cleanup
description: >
  Remove stale worktrees for closed stories older than 7 days. This helps keep
  the repository clean and prevents accumulation of old worktrees. Use when the
  user says "/cleanup", "clean up worktrees", or "remove old worktrees".
---

# Stale Worktree Cleanup

Remove worktrees for stories that are closed and older than 7 days.

## Procedure

1. **List all worktrees**
   - Run `git worktree list` in the project root
   - Parse each line to extract the worktree path and branch name (format: `/path  <sha>  [branch-name]`)
   - Skip the main worktree (the repo root itself)

2. **Load epics.json**
   - Read `.claude/epics.json` from the project root
   - Extract all stories with their `state` and `branch` fields

3. **Match and filter**
   - For each worktree, find the corresponding story by matching the branch name
   - Keep only worktrees where:
     - The story's `state` is `closed`
     - The worktree directory's modification time (mtime) is older than 7 days
   - To check mtime on macOS: run `stat -f %m <worktree-path>` and compare to `$(date +%s) - 604800`

4. **Present stale worktrees**
   - Display a numbered list of stale worktrees:
     ```
     Stale worktrees (closed stories, older than 7 days):
     1. /path/to/worktree1  (story-NNN: <title>)
     2. /path/to/worktree2  (story-NNN: <title>)
     ```
   - If none found, print "No stale worktrees found." and stop

5. **Confirm with user**
   - Ask: "Remove these worktrees? (yes/no)"
   - Use `AskUserQuestion` to get confirmation

6. **Remove confirmed worktrees**
   - For each confirmed worktree, run: `git worktree remove <path>`
   - If removal fails (e.g., uncommitted changes), report the error and continue with the next worktree
   - After all removals, report: "Removed N worktrees" or "Failed to remove X worktrees"

## Edge cases

- **Worktree with uncommitted changes**: `git worktree remove` will fail. Report the failure to the user and continue.
  - Only add `--force` flag if the user explicitly requests it
- **Story with `branch: null`**: No worktree to match; skip it
- **Branch name mismatch**: If a worktree's branch doesn't match any story in epics.json, skip it (it's likely a manual worktree)
