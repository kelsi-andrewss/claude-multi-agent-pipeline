---
name: run-stories
description: >
  Execute stories in parallel (where safe) using background agents, each working in
  an isolated git worktree branched from a shared dev branch. Handles dependency
  ordering, write-file conflict detection, and reports results.
  Use when the user says "/run-stories", "/run-stories story-NNN", "/run-stories epic-NNN",
  or any combination of story and epic IDs.
args:
  - name: args
    type: string
    description: >
      Optional. Zero or more space-separated tokens: story-NNN IDs, epic-NNN IDs,
      or nothing (runs all ready/draft stories across all active epics).
---

# Run Stories Skill Invoked

User has requested: `/run-stories {{args}}`

## Output policy
- Do not emit any text between tool calls. Run all tools silently.
- The only output is the final summary. No execution plan block, no progress narration.

## Step 0: Parse flags

- `--project-root <path>` — override project root (default: cwd). Use when target codebase is in a different repo.

All `<project-root>` references throughout use the resolved value.

## Run state management

```bash
SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
python3 ~/.claude/scripts/init-run-db.py --session-id "$SESSION_ID" --dev-branch dev
```

If init fails (exit code 2), stop: "Run state initialization failed."

## Script output handling

All scripts emit JSON on stdout. Exit codes: 0 = success, 1 = functional error, 2 = system error.

If JSON parse fails: build-verify → FAIL; diff-gate → warning; worktree-setup → BLOCKED; worktree-cleanup → note; merge-gate → BLOCKED.

## Phases

Read each phase file as you enter it. Only read the phase you're currently executing.

1. **Resolve** → Read [resolve.md](resolve.md)
   - Delegate story resolution, conflict detection, dev branch setup to a foreground subagent
   - Returns EXECUTION_PLAN and STORIES data

2. **Execute** → Read [execute.md](execute.md)
   - Launch coder agents (and test agents when test_files present) in parallel batches
   - Coder prompt template: [coder-prompt.md](coder-prompt.md)
   - Test agent template: [test-agent.md](test-agent.md)
   - Handles context sharding for >8 stories, sequential batch rebasing, health monitoring

3. **Validate** → Read [validate.md](validate.md)
   - Collect agent results, handle NEED_DECISION/NEED_RESEARCH
   - Fix-loop on build failures: [fix-integration.md](fix-integration.md)
   - Diff gate, per-story testing: [merge-gate.md](merge-gate.md)
   - Invoke `/merge-worktree` for validated stories

4. **Report** → Read [report.md](report.md)
   - Print final summary, run cleanup:
     ```bash
     python3 ~/.claude/scripts/cleanup_run_state.py --session-id "$SESSION_ID"
     ```

## Child files
- [resolve.md](resolve.md) — Story resolution, dependency ordering, conflict detection
  - [conflicts.md](conflicts.md) — pm_check_conflicts, symbol granularity, hybrid git merge-tree
- [execute.md](execute.md) — Coder launch, batch management, health monitoring
  - [coder-prompt.md](coder-prompt.md) — Full coder agent prompt template
  - [test-agent.md](test-agent.md) — Test agent prompt, BLOCKED retry logic
- [validate.md](validate.md) — Result collection, NEED_DECISION handling, diff gate
  - [fix-integration.md](fix-integration.md) — Fix-loop delegation for build/test failures
  - [merge-gate.md](merge-gate.md) — Merge gate procedure, retry by classification
- [report.md](report.md) — Final summary format
