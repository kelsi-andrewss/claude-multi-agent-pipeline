---
name: status
description: >
  Show current pipeline state: all epics and their stories with state,
  branch, and flags. Use when the user says "/status", "show pipeline
  status", "what stories are running", or "what's the current state".
  Read-only — does not modify any files or launch any agents.
---

# Pipeline Status

Read `.claude/epics.json` and print a summary table.

## Output format

For each epic (skip epics where all stories are `closed` unless `--all` is implied by context):

```
Epic: <epic-id> — <title>  [branch: <branch> | PR #<n>]
  story-NNN  [state]  <title>
    branch: <branch>
    files: <writeFiles count> write targets
    needsTesting: yes/no  needsReview: yes/no
    dependsOn: [story-ids] (if present)
```

For `running` stories, also show:
- Worktree path (from `git worktree list`)
- Any in-progress `TaskList` entries for that story

After the table, print one of:
- "No stories currently running."
- "Running: story-NNN (<title>) — worktree at <path>"
- "Blocked: story-NNN (<title>) — [reason if known]"
- "Queued: story-NNN (<title>) — waiting for: [blocking story IDs]"

Do NOT read ORCHESTRATION.md. Do NOT launch any agents. This is pure read + display.
