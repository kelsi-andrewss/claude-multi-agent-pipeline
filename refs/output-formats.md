# Output Formats

## Orchestrator output — STAGING_PAYLOAD

```
SUMMARY
Todo: <one-line description>
Story: <storyId> -- <story title> [NEW if creating]
Epic: <epicId> -- <epic title> [NEW if creating]
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>
Trivial: <yes|no>
Files:
  write: <comma-separated files the coder will modify>
  read: <comma-separated files needed for context only>
Plan: <one sentence describing what the coder will do>
Coder groups: <see coder groups format below>
STAGING_PAYLOAD written to: $TMPDIR/staging-<todo-slug>.json
```

### Coder groups format

```
Group 1 [architect|quick-fixer]: todo-xxx -- <one-line rationale>
Group 2 [quick-fixer]: todo-yyy, todo-zzz -- <one-line rationale>
Sequential after group 1: todo-aaa -- <reason for dependency>
```

## Orchestrator output — NEEDS_PLANNING

```
NEEDS_PLANNING
Todo: <one-line description>
Complexity: <low|medium|high>
Touches: <comma-separated areas>
Files explored: <comma-separated files already read>

Questions:
- <specific, actionable question>
- <specific, actionable question>

Suggestions:
- <approach the orchestrator leans toward, if any>
```

Rules: 2-8 questions. Each must be specific and independently answerable.

## Orchestrator output — UNRESOLVABLE

```
UNRESOLVABLE
Todo: <one-line description>
Reason: <why this cannot be staged>
```

## Epic-planner output (epic mode)

```
EPIC_PLAN
Epic: <epic-id> -- <epic title>
Stories: <count>

STORY <n>
Title: <story title>
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>
Trivial: <yes|no>
Files:
  write: <comma-separated>
  read: <comma-separated>
Plan: <one sentence>

...repeat for each story...

STAGING_PAYLOAD
<valid JSON array of story staging payloads>
```

## Epic-planner output (planning mode)

```
PLANNING_RESULT
Original task: <one-line>
Questions resolved: <count>

## Decisions
- Q: <question>
  A: <answer>
  Rationale: <one sentence>

## Recommended approach
<2-5 sentences>

## Scope
Write files: <comma-separated>
Read files: <comma-separated>
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>

## Constraints and edge cases
- <bullet>
```

## Coder return length caps

- Coder (success): 1 line -- "done: <what changed>"
- Coder (deviation/decision): <=5 lines
- Coder (error/blocked): uncapped -- include full error output
- Reviewer (PASS): 1 line
- Reviewer (BLOCKING): <=10 lines per finding, uncapped on error
- git-ops (success): 1 line
- git-ops (error): uncapped
- unit-tester (PASS): 1 line -- "tests passed: <N> tests"
- unit-tester (FAIL): uncapped -- full output for log + re-delegation
