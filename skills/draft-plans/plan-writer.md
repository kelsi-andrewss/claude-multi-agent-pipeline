# Plan Writer

## Step 3b: Launch plan-writer agents

### Frontend/mixed — gemini_design call (before agent launch)

For stories with `frontend: true` or `mixed: true`:
1. `ToolSearch: select:mcp__gemini__gemini_design`
2. `gemini_design(paths=<write_files>, output="plans/<plan-name>-design.md")`
3. Read output, store as `gemini_design_spec`

Backend-only stories skip this.

### Fast-path stories

Write directly in main session. **Backend template:**
```
# <story title>
Story: <story_id>
Agent: <agent>

## Context
<story title>
Files: <write_files>

<If decision_constraints:>
## Decision Constraints
<verbatim from query_project_decisions>

## What changes
| File | Change |
|---|---|
| <write_file> | <task description> |

<!-- CODER_ONLY -->
## Tasks
1. <task 1>
<!-- END_CODER_ONLY -->

## Acceptance criteria
- <one testable statement per task>

## Verification
- Confirm each task implemented correctly
- No changes outside write scope
<!-- TESTER_ONLY -->
<!-- END_TESTER_ONLY -->
```

**Frontend fast-path template:** Same but adds `## Frontend Design (Gemini)` (verbatim from gemini_design_spec) and `## Architecture (Claude)` (state management, data flow) between What changes and Tasks.

### Agent-path stories

Launch one `general-purpose` background agent per story. Prompt:

```
You are writing a plan file for story <story_id>: "<title>"

Agent: <agent>
Tasks: <task list>
Write files: <write_files>
Read files: <read_files>
Output file: plans/<name>.md

<If predicted preferences:> ## Predicted Preferences
<If decision_constraints:> ## Decision Constraints (include verbatim in plan)
<If exemplar_conventions:> ## Exemplar Conventions (include verbatim in plan)
<If frontend/mixed:> ## Gemini Design Spec (include verbatim as ## Frontend Design (Gemini))

## Critique Checklist
<content from refs/orch-critique-checklist.md>

## Instructions
1. Read write_files to understand current state.
2. Read files referenced by tasks but not in write_files → read-only context.
   Identify all new/modified public interfaces.
3. Apply critique checklist. SIGNIFICANT issues → NEED_DECISION. MINOR gaps → incorporate.
3.5. Extract function/class signatures → write ## Contract section.
3.6. Convert tasks to testable acceptance criteria (given/when/then). If test_files, reference specific test file per criterion.
3.7. Frontend stories: criteria MUST describe observable user flows, not structural facts.
     Right: "User types message, clicks Send → message appears, input clears, list scrolls"
     Wrong: "ChatPanel component exists"
4. Write plan file with structure: Context, Decision Constraints, What changes, Frontend Design (if applicable), Architecture (if applicable), Read-only context (CODER_ONLY), Contract, Tasks (CODER_ONLY), Acceptance criteria, Verification, TESTER_ONLY block.
4.5. Wrap Tasks and Read-only context in <!-- CODER_ONLY --> delimiters.
5. If briefing_path provided, include in read-only context.
6. Return: "DONE: plans/<name>.md"
```

If `briefing_path` set, append: `Briefing path: <path>. Include in read-only context.`

## Step 3c: Collect results

- **DONE** → `pm_update_story(story_id, plan_file="plans/<name>.md")`
- **NEED_DECISION** → surface to user, resume agent
- **BLOCKED** → report, skip

**Frontend validation:** For frontend/mixed stories, verify both `## Frontend Design (Gemini)` and `## Architecture (Claude)` are present and non-empty. Missing → reject, retry once. Second failure → BLOCKED.

Also update DB for fast-path stories.
