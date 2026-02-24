---
name: deps
description: >
  Visualize story dependencies: show all non-closed stories grouped by epic with
  dependency status. Each story is marked READY (no open blockers) or WAITING
  (blocked by one or more open stories). Closed stories are shown for context
  but not marked. Use when the user says "/deps", "show dependencies", "what's
  blocking what", or "dependency graph".
  Read-only — does not modify any files or launch any agents.
---

# Story Dependency Visualization

Read `.claude/epics.json` and print a dependency graph showing all non-closed stories and how they depend on each other.

## Output format

For each epic (skip epics where all stories are `closed`):

```
Epic: <epic-id> — <title>
  story-NNN [closed]
  story-NNN [state] READY  (depends on: story-XXX ✓ story-YYY ✓)
  story-NNN [state] WAITING  (blocked by: story-XXX story-YYY)
```

Rules:
- Show all stories in the epic, including closed ones (marked with [closed] tag)
- For non-closed stories:
  - Mark READY if `dependsOn` is empty OR all stories in `dependsOn` are `closed`
  - Mark WAITING if any story in `dependsOn` is NOT `closed` — list those blocking story IDs
  - Closed stories shown as blockers should have a checkmark (✓) when they appear in the "depends on" line
- Group stories under their epic
- Do not mark closed stories as READY or WAITING (they are context only)

## Example output

```
Epic: epic-022 — Pipeline self-hosting and capability expansion
  story-164 [closed]
  story-165 [filling] READY  (depends on: story-164 ✓)
  story-166 [filling] WAITING  (blocked by: story-165)
  story-167 [filling] WAITING  (blocked by: story-165 story-166)
  story-168 [filling] READY
  story-169 [filling] WAITING  (blocked by: story-168)
```

## Algorithm

Use python3 to parse `.claude/epics.json`:

1. Load the JSON file
2. For each epic with at least one non-closed story:
   a. Print the epic header
   b. For each story in the epic (in order):
      - If `state` is `closed`: print `  story-NNN [closed]`
      - If `state` is not `closed`:
        - Collect all stories from `dependsOn` list
        - Check if all dependsOn stories are closed:
          - If yes: print `  story-NNN [state] READY  (depends on: story-IDs ✓)`
          - If no: find which ones are NOT closed and print `  story-NNN [state] WAITING  (blocked by: story-IDs)`
        - If `dependsOn` is empty: print `  story-NNN [state] READY`

Do NOT read ORCHESTRATION.md. Do NOT launch any agents. This is pure read + display.
