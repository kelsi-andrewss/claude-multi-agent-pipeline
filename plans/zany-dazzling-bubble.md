# Plan: Reduce Wasted Output in merge-epic Skill Execution

## Context

When `/merge-epic` was run, the main session executed multiple small Python probes against `epics.json` — each spawning a new process and printing intermediate diagnostic output to the conversation. This is noisy and unnecessary. The root cause is the main session doing incremental exploration rather than reading the skill file once and executing its steps cleanly.

The skill file (`skills/merge-epic/SKILL.md`) is well-structured. The problem is behavioral: the main session is treating skill execution as an exploration task instead of a procedural task.

## What needs to change

The fix is **not** in the skill file — it's in how the main session executes skills. Two things cause the noise:

1. **Multiple small Python probes**: The main session reads `epics.json` in 4-5 separate Python one-liners to incrementally discover the epic structure, story states, and PR number. These should be one consolidated read.

2. **Printing intermediate findings**: Each probe echoes its result to the conversation. Only the final result (pass/fail, what to do next) should be shown.

## Fix

**File**: `/Users/kelsiandrews/.claude/CLAUDE.md`

Add a rule under a new `## Skill execution` section (or append to existing relevant section):

```
## Skill execution
- When executing a skill, read the skill file ONCE, then execute its numbered steps in order.
- For epics.json reads: extract all needed fields (epic state, story states, prNumber, isDraft) in a single read or single script — never probe incrementally.
- Only output to the conversation when a step requires user input, produces an error, or is the final result. Suppress intermediate probe output.
```

**File**: `/Users/kelsiandrews/.claude/skills/merge-epic/SKILL.md`

Add a note to step 1 making it explicit:

```
1. **Read** `.claude/epics.json` once. In a single pass, extract: epic record, all story states, prNumber, and epic state. Do not probe epics.json multiple times.
```

## Files to modify

- `/Users/kelsiandrews/.claude/CLAUDE.md` — add skill execution rule
- `/Users/kelsiandrews/.claude/skills/merge-epic/SKILL.md` — add single-read note to step 1

## Verification

Run `/merge-epic` (or `/status`) after the change. The conversation should show only:
1. The skill reading epics.json (silent)
2. A single structured output (merge-ready list or error)
— no intermediate Python probe results.
