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

## ANSI color map

Apply these ANSI escape codes when rendering story fields. Use `\033[0m` to reset after each colored value.

| Field value | ANSI code |
|---|---|
| State: `running` | `\033[32m` (green) |
| State: `testing` | `\033[36m` (cyan) |
| State: `reviewing` | `\033[36m` (cyan) |
| State: `merging` | `\033[33m` (yellow) |
| State: `blocked` | `\033[31m` (red) |
| State: `queued` | `\033[2m` (dim) |
| State: `filling` | `\033[2m` (dim) |
| State: `closed` | `\033[2m` (dim) |
| Agent: `architect` | `\033[35m` (magenta) |
| Agent: `quick-fixer` | `\033[34m` (blue) |
| Agent: `manual` | `\033[37m` (white/plain) |
| Model: `opus` | `\033[1;31m` (bold red) |
| Model: `sonnet` | `\033[33m` (yellow) |
| Model: `haiku` | `\033[32m` (green) |
| Epic header | `\033[1m` (bold) |

## Output format

For each epic (skip epics where all stories are `closed` unless `--all` is implied by context):

```
\033[1mEpic: <epic-id> — <title>\033[0m  [branch: <branch> | PR #<n>]
  story-NNN  \033[<state-color>m[state]\033[0m  <title>  \033[<agent-color>m<agent>\033[0m  \033[<model-color>m<model>\033[0m
    branch: <branch>
    files: <writeFiles count> write targets
    needsTesting: yes/no  needsReview: yes/no
    dependsOn: [story-ids] (if present)
```

- Omit `agent` and `model` columns if the story has no `agent`/`model` fields (backward-compatible with old stories).
- The brackets around `[state]` always appear — they visually group the value even without color support.

For `running` stories, also show:
- Worktree path (from `git worktree list`)
- Any in-progress `TaskList` entries for that story

After the table, print one of:
- "No stories currently running."
- `\033[32mRunning\033[0m: story-NNN (<title>) — worktree at <path>`
- `\033[31mBlocked\033[0m: story-NNN (<title>) — [reason if known]`
- `\033[2mQueued\033[0m: story-NNN (<title>) — waiting for: [blocking story IDs]`

Do NOT read ORCHESTRATION.md. Do NOT launch any agents. This is pure read + display.
