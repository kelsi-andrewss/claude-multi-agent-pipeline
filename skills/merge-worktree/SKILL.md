---
name: merge-worktree
description: >
  Merge a story worktree branch into its dev branch, push, clean up the worktree and branches,
  and mark the story done. Use when the user says "/merge-worktree", "/merge-worktree story-NNN",
  or "merge worktree".
args:
  - name: args
    type: string
    description: >
      Optional. A single story ID (story-NNN) to merge, or empty to auto-detect the most
      recently modified story worktree under .claude/worktrees/story/.
      Or "--queue" to auto-merge all done stories with active worktrees in dependency order.
      Or "--queue --dry-run" to preview what would be merged without executing.
---

# Merge Worktree Skill Invoked

User has requested: `/merge-worktree {{args}}`

## Decision rules (from ORCHESTRATION §8)

- **NEED_DECISION**: main session picks option, resumes coder. Story stays `in-progress`.
- **Escalation**: 2 BLOCKING → Opus (architect only). Still BLOCKING → `blocked`.
- **Restart**: plan was wrong → new plan, same model, max 1. Second failure → `blocked`.
- **Restart vs escalation**: coder did what plan said and it didn't work → restart. Coder couldn't execute a sound plan → escalation.

## Output policy
- No text between tool calls. Only the final report.

## Mode routing

Parse `{{args}}` to determine mode, then read the appropriate child file:

1. **Queue mode** (`--queue` in args) → Read [queue.md](queue.md)
   - Auto-discovers all done stories with active worktrees
   - Dependency-ordered merge with hold list support

2. **Batch mode** (called by run-stories/ship with 2+ story IDs) → Read [batch.md](batch.md)
   - Single subagent merges multiple stories via merge-queue.py
   - Queue-based coordination for non-conflicting parallel merges

3. **Single mode** (one story ID or no args) → Read [single.md](single.md)
   - Resolve story/worktree, test, merge, cleanup, update DB
   - Testing gates: [testing.md](testing.md)
   - Post-merge: [outcome.md](outcome.md)

## Child files
- [single.md](single.md) — Steps 1–6: resolve, test, merge, cleanup, DB update, report
  - [testing.md](testing.md) — Steps 2.5–2.6: smoke test, test validation, coverage, project tests
  - [outcome.md](outcome.md) — Steps 5.5–5.7: outcome logging, regression check, divergence capture
- [batch.md](batch.md) — Subagent delegation, diff gate, queue protocol
- [queue.md](queue.md) — Auto-discover, hold list, dependency order, execute
