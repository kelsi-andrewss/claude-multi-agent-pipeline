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
| State: `in-progress` | `\033[32m` (green) |
| State: `in-review` | `\033[36m` (cyan) |
| State: `approved` | `\033[33m` (yellow) |
| State: `blocked` | `\033[31m` (red) |
| State: `ready` | `\033[2m` (dim) |
| State: `draft` | `\033[2m` (dim) |
| State: `done` | `\033[2m` (dim) |
| State: `shipped` | `\033[2;34m` (dim blue) |
| Agent: `architect` | `\033[35m` (magenta) |
| Agent: `quick-fixer` | `\033[34m` (blue) |
| Agent: `manual` | `\033[37m` (white/plain) |
| Model: `opus` | `\033[1;31m` (bold red) |
| Model: `sonnet` | `\033[33m` (yellow) |
| Model: `haiku` | `\033[32m` (green) |
| Epic header | `\033[1m` (bold) |

## Labels

Use human-readable labels derived from titles, not numeric IDs:

- **Epic label**: kebab-case slug of the epic title, max 5 words (e.g. `pipeline-self-hosting`)
- **Story label**: kebab-case slug of the story title, max 5 words (e.g. `merge-epic-skill-update`)
- The numeric IDs (`epic-NNN`, `story-NNN`) are shown in parentheses after the label for reference

## Output format

For each epic (skip epics where all stories are `done` or `shipped` unless `--all` is implied by context):

```
\033[1mEpic: <epic-slug> (<epic-id>) — <title>\033[0m  [branch: <branch> | PR #<n>]  state: <epic-state>
  <story-slug> (<story-id>)  \033[<state-color>m[state]\033[0m  <title>  \033[<agent-color>m<agent>\033[0m  \033[<model-color>m<model>\033[0m  (<task-progress>)
    branch: <branch>
    files: <writeFiles count> write targets
    needsTesting: yes/no  needsReview: yes/no
    dependsOn: [<story-slugs>] (if present)
```

- Omit `agent` and `model` columns if the story has no `agent`/`model` fields (backward-compatible with old stories).
- The brackets around `[state]` always appear — they visually group the value even without color support.
- `dependsOn` lists use story slugs, not numeric IDs.

### Task progress for code stories

If the story has a `tasks` array, show task progress after the model:
```
add-oauth-login (story-042)  [in-progress]  Add OAuth login  architect  sonnet  (1/4 tasks)
```

### Checklist progress for manual stories

For `agent: "manual"` stories, read the checklist file from `writeFiles[0]` and count `[x]` vs `[ ]`:
```
checklist-deploy (story-088)  [in-progress]  Checklist: deploy  manual  (2/4 steps)
```

### Backlog section

If the backlog epic exists and has stories, show it separately at the end:
```
Backlog (3 stories):
  investigate-caching (story-099)  [draft]  Investigate caching strategy
  research-websocket-alternatives (story-100)  [draft]  Research WebSocket alternatives
  audit-unused-dependencies (story-101)  [draft]  Audit unused dependencies
```

For `in-progress` stories, also show:
- Worktree path (from `git worktree list`)
- Any in-progress `TaskList` entries for that story

After the table, print one of:
- "No stories currently in-progress."
- `\033[32mIn-progress\033[0m: <story-slug> (<story-id>) — worktree at <path>`
- `\033[31mBlocked\033[0m: <story-slug> (<story-id>) — [reason if known]`
- `\033[2mReady\033[0m: <story-slug> (<story-id>) — waiting for: [blocking story slugs]`

### Quick actions footer

```
Actions: /run-story <slug-or-id> | /defer <slug-or-id> | /checklist <name> | /backlog promote <slug-or-id> <epic>
```

Note: `/run-story`, `/defer`, `/move`, and other skills accept either the numeric ID or the slug as input.

Do NOT read ORCHESTRATION.md. Do NOT launch any agents. This is pure read + display.
