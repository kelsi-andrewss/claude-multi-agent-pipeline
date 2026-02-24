# Plan: Rewrite ORCHESTRATION.md

## Context
The current ORCHESTRATION.md (576 lines) is hard to follow because:
1. The same concept appears in 3+ places (diff gate, simple-fix policy, model selection, protected files warning)
2. Sections are organized by topic cluster, not execution flow — so following the pipeline requires jumping back and forth
3. Conflict resolution between rules is implicit (e.g. simple-fix vs. worktree threshold)

The goal is a full rewrite that: preserves every rule, eliminates redundancy, and flows in execution order. No rules are added or removed — only reorganized and deduplicated.

## Target structure (execution flow order)

```
1. ENFORCEMENT (zero-skip rule + corollaries) — read first, applies everywhere
2. AGENT ROLES — what each agent type is and is not allowed to do (single definition)
3. MODEL SELECTION — single decision table for all roles
4. INCOMING REQUEST → ORCHESTRATION — when to use orchestrator, when to skip, preprocessing
5. ORCHESTRATOR OUTPUT FORMAT — strict template + staging payload schema
6. STAGING PAYLOAD VALIDATION — required fields, failure handling
7. EPIC / STORY STRUCTURE — epics.json schema, state machine diagram
8. FILL PHASE — default behavior after payload approval
9. RUN TRIGGER — step-by-step worktree creation sequence
10. CODER GROUPING — decision tree + task size ceiling + prompt requirements (single place)
    └── Protected files boilerplate (defined once, referenced in prompt requirements)
11. PIPELINE EXECUTION — coder tasks → diff gate → testing? → reviewing? → merge
    └── Diff gate (defined once, fully)
    └── Simple-fix policy (defined once, with explicit precedence: worktree threshold overrides)
    └── Unit-tester (on-demand trigger conditions + prompt)
    └── Reviewer (on-demand trigger conditions + prompt + send-back budget)
    └── Escalation
12. STORY MERGE SEQUENCE — inline bash steps
13. EPIC MERGE SEQUENCE — user-triggered bash steps
14. PARALLEL STORY EXECUTION — overlap check, merge ordering, batch window
15. CROSS-SESSION RECOVERY — snapshot triggers, recovery sources, session-start procedure
16. BACKGROUND AGENT MANAGEMENT — check-in cadence, stale detection, context clearing
17. LOGGING — test failure log format, review-findings, architectural findings check
18. TOKEN OPTIMIZATIONS — coder prompt limit, CSS-only shortcut, inline parallelism
```

## Key consolidations

| Concept | Currently in | After rewrite |
|---|---|---|
| Diff gate procedure | TaskCompleted handling + Branch/merge rules (2x) | §11 PIPELINE, referenced by name in §12 |
| Simple-fix policy | Story pipeline + Agent execution rules + TaskCompleted (3x) | §11 PIPELINE, one definition with explicit precedence note |
| Model selection | Todo orchestration + Pipeline order + Agent execution rules (3x) | §3 MODEL SELECTION, one table |
| Protected files boilerplate | Coder grouping section (full list + verbatim line) | §10 CODER GROUPING, referenced from prompt requirements |
| Unit-tester trigger conditions | Story pipeline + Pipeline order (2x) | §11 PIPELINE, one list |
| Reviewer on-demand conditions | Story pipeline + Pipeline order (2x) | §11 PIPELINE, one definition |
| Worktree creation steps | Run trigger + Epic branch lifecycle (2x) | §9 RUN TRIGGER, one sequence |

## Explicit precedence rules to add (currently implicit)

1. **Simple-fix vs. worktree threshold**: "Worktree threshold takes precedence. Simple-fix policy only applies when the file is not protected and the total change touches ≤2 files."
2. **Reviewer send-back budget**: "After 2 BLOCKING reviews, escalate coder to Opus for 1 final attempt. Budget does not reset after escalation. If Opus attempt is still BLOCKING → `blocked`."
3. **Novel findings check**: "Novel = not already present as a bullet in CLAUDE.md (grep for 3+ key terms before appending)."

## File to edit
`/Users/kelsiandrews/.claude/ORCHESTRATION.md`

## Verification
- Line count should decrease (target: ~350-400 lines from 576)
- Every rule from the original must be present — do a diff-level check after rewrite
- Read the result top-to-bottom and confirm it follows a "request arrives → what happens next" narrative
- No new rules introduced; no existing rules removed
