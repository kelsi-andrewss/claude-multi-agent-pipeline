---
name: deps
description: >
  Show a dependency tree for all stories in epics.json. Use when the user
  says "/deps", "show dependencies", "what depends on what", or "show story
  tree". Read-only — does not modify any files or launch any agents.
---

# Story Dependency Visualization

Read `.claude/epics.json` and render an ASCII dependency tree grouped by epic.

## ANSI color map

Apply these ANSI escape codes when rendering story state. Use `\033[0m` to reset after each colored value.

| State | ANSI code |
|---|---|
| `running` | `\033[32m` (green) |
| `testing` | `\033[36m` (cyan) |
| `reviewing` | `\033[36m` (cyan) |
| `merging` | `\033[33m` (yellow) |
| `blocked` | `\033[31m` (red) |
| `queued` | `\033[2m` (dim) |
| `filling` | `\033[2m` (dim) |
| `closed` | `\033[2m` (dim) |
| Epic header | `\033[1m` (bold) |

## Algorithm

1. Parse all stories from every epic in `epics.json`.
2. Build a dependency map: for each story, note which stories it `dependsOn`.
3. Find root stories — stories whose `dependsOn` list is empty or absent.
4. For each epic, render the epic header, then render a tree rooted at root stories, recursively attaching dependents.
5. If a story has no dependents and no `dependsOn`, render it as a standalone leaf under the epic.

A story is **ready to run** when its state is `filling` and every story in its `dependsOn` list has state `closed`. Mark those with `<- ready` in plain text (no extra color needed; the state color already distinguishes them).

## Tree rendering rules

- Epic header: `\033[1m<epic-id>\033[0m  <epic-title>`
- Root stories (no `dependsOn` or empty list) are direct children of the epic header.
- Child stories (stories that `dependsOn` a rendered story) are nested one level deeper.
- Use `├──` for non-last siblings and `└──` for the last sibling at each level.
- Continuation lines for deeper nesting use `│   ` (pipe + spaces) under `├──` parents and `    ` (four spaces) under `└──` parents.
- Story line format:
  ```
  <connector> <story-id> \033[<state-color>m[<state>]\033[0m <title><ready-marker>
  ```
  where `<ready-marker>` is `  <- ready` when the story qualifies, otherwise empty.

## Example output

```
epic-022  Pipeline self-hosting and capability expansion
  └── story-164 [closed] Bootstrap pipeline directory structure and scripts
      ├── story-165 [running] Automated PR description generation
      ├── story-166 [running] epics.json health check skill
      ├── story-167 [running] Story dependency visualization skill
      ├── story-182 [filling] Sparse-checkout worktrees with sparseOk flag  <- ready
      └── story-168 [running] Coder prompt templates
story-183 [closed] /audit skill — codebase audit via Opus agent
story-184 [closed] /quick skill — bypass pipeline for small iterative changes
```

Stories with no `dependsOn` and no dependents are rendered directly under the epic header as standalone lines (no tree connector prefix needed when they are the sole root).

## Flags

- `--all` — include epics where all stories are `closed` (default: skip fully-closed epics)
- `--epic <id>` — filter to a single epic

## Constraints

Do NOT read ORCHESTRATION.md. Do NOT modify any files. Do NOT launch any agents. This is pure read + display.
