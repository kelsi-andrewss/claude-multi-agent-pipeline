---
name: health
description: >
  Run a structural health check on .claude/epics.json and report any
  issues. Use when the user says "/health", "check epics health", "validate
  epics.json", or "are there any broken stories". Read-only — does NOT
  modify any files or launch any agents.
---

# epics.json Health Check

Read `.claude/epics.json` and run each check below. Print a health report
with a pass/warn/fail status per check.

## ANSI color map

| Status | ANSI code |
|---|---|
| PASS | `\033[32m` (green) |
| WARN | `\033[33m` (yellow) |
| FAIL | `\033[31m` (red) |
| Section header | `\033[1m` (bold) |

Reset with `\033[0m` after each colored value.

## Checks to run

### 1. Stories missing agent or model

Iterate every story across all epics. Flag any story whose `agent` field is
absent or null, or whose `model` field is absent or null. Skip stories in
`closed` state — those may legitimately predate the fields.

- PASS: all non-closed stories have both fields
- FAIL: list each offending story id and title, noting which field is missing

### 2. Running stories with no branch

Find stories where `state == "running"` and `branch` is null or empty string.

- PASS: all running stories have a branch
- FAIL: list each offending story id and title

### 3. Running stories with no worktree

For each story where `state == "running"`, check whether a worktree whose
path contains the branch name exists by running:

```
git worktree list
```

Match each running story's `branch` value against the worktree paths listed.
A story is flagged if no worktree path contains the branch name as a substring.

- PASS: every running story has a matching worktree
- WARN: list each running story id and branch that has no active worktree
  (warn rather than fail because a story may legitimately be running without
  a worktree if it was just created)

### 4. Epic branches with no PR

For each epic in `epics`, check whether `prNumber` is null or absent while
the epic's `branch` exists locally. Detect the branch by running:

```
git branch --list <branch>
```

- PASS: every epic branch that exists locally also has a prNumber
- WARN: list each epic id and branch that exists locally but has no prNumber

### 5. Broken dependsOn references

Collect all story IDs across all epics into a set. Then for every story,
check each entry in its `dependsOn` array. Flag any reference that does not
appear in the collected set.

- PASS: all dependsOn references resolve to known story IDs
- FAIL: list each offending story id, the bad reference, and the title

### 6. Ready-to-run candidates (filling stories with all deps closed)

Find stories where `state == "filling"`. For each, check whether every story
ID listed in `dependsOn` has `state == "closed"`. If yes, the story is
eligible to be queued.

- PASS (no candidates): no filling stories are ready
- WARN (candidates found): list each ready story id and title with the note
  "all dependencies closed — eligible to queue"

## Output format

```
\033[1mepics.json Health Report\033[0m

\033[1m[1] Stories missing agent/model\033[0m
  \033[32mPASS\033[0m  all non-closed stories have agent and model

\033[1m[2] Running stories with no branch\033[0m
  \033[31mFAIL\033[0m  story-NNN (<title>) — missing: branch

\033[1m[3] Running stories with no worktree\033[0m
  \033[33mWARN\033[0m  story-NNN branch story/foo — no active worktree found

\033[1m[4] Epic branches with no PR\033[0m
  \033[33mWARN\033[0m  epic-NNN branch epic/foo — branch exists locally but prNumber is null

\033[1m[5] Broken dependsOn references\033[0m
  \033[32mPASS\033[0m  all dependsOn references resolve

\033[1m[6] Ready-to-run candidates\033[0m
  \033[33mWARN\033[0m  story-NNN (<title>) — all dependencies closed, eligible to queue

Summary: N checks passed, N warnings, N failures
```

Print the summary line at the end using the appropriate color for the worst
severity found (green if all pass, yellow if any warn, red if any fail).

Do NOT modify any files. Do NOT launch any agents. This is pure read + display.
